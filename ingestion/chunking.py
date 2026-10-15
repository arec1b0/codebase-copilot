"""Partition source at syntax boundaries and bound every emitted snippet."""

import ast
import bisect
import hashlib
import re
import uuid
from dataclasses import dataclass

import tree_sitter_cpp
import tree_sitter_go
from tree_sitter import Language, Node, Parser

from ingestion.models import Chunk, LanguageName


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    symbol: str | None
    kind: str


def line_starts(text: str) -> list[int]:
    return [0, *(match.end() for match in re.finditer("\n", text))]


def char_position(text: str, starts: list[int], row: int, byte_column: int) -> int:
    start = starts[row]
    end = starts[row + 1] if row + 1 < len(starts) else len(text)
    prefix = text[start:end].encode("utf-8")[:byte_column].decode("utf-8")
    return start + len(prefix)


def python_spans(text: str, starts: list[int], *, methods: bool = False) -> list[Span]:
    module = ast.parse(text)
    spans = []
    for node in module.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        start = char_position(text, starts, node.lineno - 1, node.col_offset)
        if node.decorator_list:
            start = starts[min(decorator.lineno for decorator in node.decorator_list) - 1]
        if node.end_lineno is None or node.end_col_offset is None:
            raise ValueError("Python did not provide complete source positions.")
        end = char_position(text, starts, node.end_lineno - 1, node.end_col_offset)
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        if methods and isinstance(node, ast.ClassDef):
            members = [
                member
                for member in node.body
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            ]
            cursor = start
            for member in members:
                member_start = starts[
                    min([member.lineno, *[d.lineno for d in member.decorator_list]]) - 1
                ]
                if member.end_lineno is None or member.end_col_offset is None:
                    raise ValueError("Python did not provide complete member positions.")
                member_end = char_position(
                    text, starts, member.end_lineno - 1, member.end_col_offset
                )
                if cursor < member_start:
                    spans.append(Span(cursor, member_start, node.name, "class"))
                member_kind = "class" if isinstance(member, ast.ClassDef) else "method"
                spans.append(
                    Span(member_start, member_end, f"{node.name}.{member.name}", member_kind)
                )
                cursor = member_end
            if cursor < end:
                spans.append(Span(cursor, end, node.name, "class"))
        else:
            spans.append(Span(start, end, node.name, kind))
    return spans


def node_symbol(node: Node) -> str | None:
    target = node.child_by_field_name("name")
    if target is None and node.type == "type_declaration":
        declarations = [
            child for child in node.named_children if child.type in ("type_spec", "type_alias")
        ]
        if len(declarations) != 1:
            return None
        target = declarations[0].child_by_field_name("name")
    if target is None:
        target = node.child_by_field_name("declarator")
        while target is not None:
            inner = target.child_by_field_name("declarator")
            if inner is None:
                break
            target = inner
    return target.text.decode("utf-8") if target is not None and target.text is not None else None


def syntax_spans(text: str, starts: list[int], language: LanguageName) -> list[Span]:
    grammar = tree_sitter_go.language() if language == "go" else tree_sitter_cpp.language()
    tree = Parser(Language(grammar)).parse(text.encode("utf-8"))
    if tree.root_node.has_error:
        raise ValueError("The syntax tree contains errors.")
    kinds = {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "type",
        "function_definition": "function",
        "class_specifier": "class",
        "struct_specifier": "struct",
    }
    spans = []
    pending = [tree.root_node]
    while pending:
        node = pending.pop()
        if node.type not in kinds:
            pending.extend(reversed(node.named_children))
            continue
        wrapper = node
        while wrapper.parent is not None and wrapper.parent.type == "template_declaration":
            wrapper = wrapper.parent
        start = char_position(text, starts, wrapper.start_point.row, wrapper.start_point.column)
        end = char_position(text, starts, wrapper.end_point.row, wrapper.end_point.column)
        spans.append(Span(start, end, node_symbol(node), kinds[node.type]))
    return sorted(spans, key=lambda item: (item.start, item.end))


def document_spans(text: str) -> list[Span]:
    headings: list[tuple[int, str]] = []
    offset = 0
    fence_character = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)", line)
        if fence_character:
            if (
                fence is not None
                and fence.group(1)[0] == fence_character
                and len(fence.group(1)) >= fence_length
                and not fence.group(2).strip()
            ):
                fence_character = ""
        elif fence is not None:
            fence_character = fence.group(1)[0]
            fence_length = len(fence.group(1))
        else:
            heading = re.match(r"^ {0,3}#{1,6}[ \t]+(.+)", line)
            if heading is not None:
                headings.append((offset, heading.group(1).strip()))
        offset += len(line)
    return [
        Span(
            heading[0],
            headings[index + 1][0] if index + 1 < len(headings) else len(text),
            heading[1],
            "section",
        )
        for index, heading in enumerate(headings)
    ]


def chunk_source(
    *,
    text: str,
    repo: str,
    commit: str,
    path: str,
    language: LanguageName,
    max_chars: int,
    method_boundaries: bool = False,
) -> tuple[list[Chunk], bool]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive.")
    starts = line_starts(text)
    fallback = False
    try:
        if language == "python":
            selected = python_spans(text, starts, methods=method_boundaries)
        elif language in ("go", "cpp"):
            selected = syntax_spans(text, starts, language)
        elif language == "markdown":
            selected = document_spans(text)
        else:
            selected = []
    except (SyntaxError, ValueError, RecursionError):
        selected = []
        fallback = True

    default_kind = "syntax_fallback" if fallback else "module"
    if language in ("markdown", "text"):
        default_kind = "document"
    regions = []
    cursor = 0
    for span in selected:
        if span.start < cursor:
            continue
        if span.start > cursor:
            regions.append(Span(cursor, span.start, None, default_kind))
        regions.append(span)
        cursor = span.end
    if cursor < len(text):
        regions.append(Span(cursor, len(text), None, default_kind))

    chunks = []
    for span in regions:
        cursor = span.start
        part = 1
        while cursor < span.end:
            end = min(cursor + max_chars, span.end)
            if end < span.end:
                newline = text.rfind("\n", cursor, end)
                if newline > cursor:
                    end = newline + 1
            snippet = text[cursor:end]
            if snippet.strip():
                digest = hashlib.sha256(snippet.encode("utf-8")).hexdigest()
                identity = f"{repo}\0{commit}\0{path}\0{cursor}\0{end}\0{digest}"
                chunks.append(
                    Chunk(
                        chunk_id=str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
                        repo=repo,
                        commit_sha=commit,
                        path=path,
                        language=language,
                        symbol=span.symbol,
                        kind=span.kind,
                        start_line=bisect.bisect_right(starts, cursor),
                        end_line=bisect.bisect_right(starts, end - 1),
                        start_char=cursor,
                        end_char=end,
                        part=part,
                        content_sha256=digest,
                        text=snippet,
                    )
                )
                part += 1
            cursor = end
    return chunks, fallback
