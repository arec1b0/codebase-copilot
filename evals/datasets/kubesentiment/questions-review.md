# KubeSentiment source-review questions

Pinned commit: `1aa3ebfd3f0467ea61142dff72d6534aa6968e20`.

Assistant-authored reference labels, awaiting human review. These are not collected production questions.

## locating-01 (locating)

Where does PredictionService.predict reject empty or whitespace-only input?

Reference: In app/services/prediction.py, PredictionService.predict checks not text or not text.strip() and raises TextEmptyError before inference.

Evidence:

- [app/services/prediction.py:76–77](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L76-L77)

## locating-02 (locating)

Where does APIKeyAuthMiddleware compare a supplied API key to the configured key?

Reference: APIKeyAuthMiddleware.dispatch in app/api/middleware/auth.py reads the configured header and uses secrets.compare_digest(provided, expected).

Evidence:

- [app/api/middleware/auth.py:81–83](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/middleware/auth.py#L81-L83)

## locating-03 (locating)

Where is the namespaced Redis cache key constructed, and what is its format?

Reference: RedisCacheClient._make_key in app/services/redis_cache.py returns namespace:cache_type:key.

Evidence:

- [app/services/redis_cache.py:71–71](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/redis_cache.py#L71-L71)

## locating-04 (locating)

Where does drift detection calculate the overall drift_score from the PSI values?

Reference: check_drift in app/services/drift_detection.py sets drift_score to (confidence_psi + length_psi) / 2.

Evidence:

- [app/services/drift_detection.py:315–316](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/drift_detection.py#L315-L316)

## locating-05 (locating)

Where does ModelFactory.create_model reuse an already cached model?

Reference: In app/models/factory.py it tests cache_key in _model_cache and returns that cached entry before backend creation.

Evidence:

- [app/models/factory.py:59–61](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/models/factory.py#L59-L61)

## locating-06 (locating)

Where does TextInput.validate_text strip leading and trailing whitespace from valid text?

Reference: TextInput.validate_text in app/api/schemas/requests.py returns v.strip() after its nonempty check.

Evidence:

- [app/api/schemas/requests.py:75–75](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/schemas/requests.py#L75-L75)

## explanation-01 (explanation)

How does PredictionService.predict add optional engineered features to the model result?

Reference: It calls the injected model with stripped text; when settings.model.enable_feature_engineering is true, it adds features from feature_engineer.extract_features on stripped text, then returns the result.

Evidence:

- [app/services/prediction.py:83–87](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L83-L87)

## explanation-02 (explanation)

How does PredictionService.predict_batch represent invalid inputs and preserve their positions?

Reference: Validation substitutes None for empty, whitespace-only, or overlength inputs. Only valid stripped inputs go to model.predict_batch. Iteration over valid_texts restores positions using an Invalid input error placeholder or the next prediction.

Evidence:

- [app/services/prediction.py:106–109](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L106-L109)
- [app/services/prediction.py:112–112](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L112-L112)
- [app/services/prediction.py:117–122](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L117-L122)

## explanation-03 (explanation)

How does RedisCacheClient.set serialize a value and pass its TTL to Redis?

Reference: It serializes with pickle.dumps and calls client.set with serialized_value and ex=ttl. The successful path returns True.

Evidence:

- [app/services/redis_cache.py:123–123](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/redis_cache.py#L123-L123)
- [app/services/redis_cache.py:124–126](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/redis_cache.py#L124-L126)

## explanation-04 (explanation)

How does should_shadow decide whether to sample a request for shadow inference?

Reference: It returns False when shadow mode is disabled or shadow_model is absent. Otherwise it compares random.random() * 100 with settings.mlops.shadow_traffic_percentage.

Evidence:

- [app/services/shadow_mode.py:161–164](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/shadow_mode.py#L161-L164)

## explanation-05 (explanation)

How does add_prediction establish the initial drift reference baseline?

Reference: Before a baseline exists, or for explicitly marked reference input, it appends prediction, confidence, and text length to reference data. At min_samples reference predictions it sets baseline_established to True.

Evidence:

- [app/services/drift_detection.py:142–142](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/drift_detection.py#L142-L142)
- [app/services/drift_detection.py:143–146](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/drift_detection.py#L143-L146)
- [app/services/drift_detection.py:149–150](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/drift_detection.py#L149-L150)

## explanation-06 (explanation)

What is the ONNX model path fallback order in ModelFactory.create_model?

Reference: The explicit model_path wins, then settings.model.onnx_model_path, then settings.model.onnx_model_path_default. The chosen path is passed to get_onnx_sentiment_analyzer.

Evidence:

- [app/models/factory.py:77–80](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/models/factory.py#L77-L80)

## dependency-01 (dependency)

Which injected collaborators does PredictionService retain during initialization?

Reference: Its constructor retains model, settings, and feature_engineer as self.model, self.settings, and self.feature_engineer.

Evidence:

- [app/services/prediction.py:51–53](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L51-L53)

## dependency-02 (dependency)

Which setting controls the maximum text length accepted by PredictionService.predict?

Reference: PredictionService.predict depends on self.settings.model.max_text_length; it compares len(text) to that value and uses it in TextTooLongError.

Evidence:

- [app/services/prediction.py:78–79](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L78-L79)

## dependency-03 (dependency)

Which reference and current data does check_drift pass to the prediction-distribution chi-squared test?

Reference: check_drift calls chi_squared_test with lists of self.reference_predictions and self.current_predictions.

Evidence:

- [app/services/drift_detection.py:292–294](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/drift_detection.py#L292-L294)

## dependency-04 (dependency)

How does the configured Redis namespace feed into the generated cache key?

Reference: The constructor takes namespace from kwargs, defaulting to kubesentiment. _make_key interpolates self.namespace, cache_type, and key separated by colons.

Evidence:

- [app/services/redis_cache.py:49–49](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/redis_cache.py#L49-L49)
- [app/services/redis_cache.py:71–71](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/redis_cache.py#L71-L71)

## dependency-05 (dependency)

How are background shadow prediction tasks tracked and removed when they finish?

Reference: dispatch_shadow_prediction creates an asyncio task, adds it to self._pending_tasks, and registers self._pending_tasks.discard as the done callback.

Evidence:

- [app/services/shadow_mode.py:187–191](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/shadow_mode.py#L187-L191)

## dependency-06 (dependency)

Which backend getter does ModelFactory.create_model call for a PyTorch model?

Reference: For backend.lower() == pytorch it imports get_sentiment_analyzer from app.models.pytorch_sentiment, calls it, and caches the returned model.

Evidence:

- [app/models/factory.py:66–71](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/models/factory.py#L66-L71)

## debugging-01 (debugging)

Why does APIKeyAuthMiddleware return 401 for a protected request with a missing or wrong API key?

Reference: After its bypass checks, dispatch reads the header; a missing key or failed secrets.compare_digest causes an auth_failure event and JSONResponse status 401 with detail Unauthorized.

Evidence:

- [app/api/middleware/auth.py:81–83](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/middleware/auth.py#L81-L83)
- [app/api/middleware/auth.py:89–89](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/middleware/auth.py#L89-L89)

## debugging-02 (debugging)

Why can a non-exempt request pass APIKeyAuthMiddleware when no API key is configured?

Reference: dispatch explicitly returns await call_next(request) when expected (settings.security.api_key) is falsey.

Evidence:

- [app/api/middleware/auth.py:68–68](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/middleware/auth.py#L68-L68)
- [app/api/middleware/auth.py:78–78](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/middleware/auth.py#L78-L78)
- [app/api/middleware/auth.py:79–79](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/middleware/auth.py#L79-L79)

## debugging-03 (debugging)

Why does PredictionService.predict raise ModelNotLoadedError even for nonempty, short text?

Reference: It checks self.model.is_ready() before calling predict and raises ModelNotLoadedError when that readiness check is false.

Evidence:

- [app/services/prediction.py:80–80](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L80-L80)
- [app/services/prediction.py:81–81](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L81-L81)

## debugging-04 (debugging)

Why can RedisCacheClient.get return None after a Redis connection error?

Reference: Its except RedisError handler records a get cache error, logs Redis GET failed, and returns None instead of propagating that RedisError.

Evidence:

- [app/services/redis_cache.py:102–105](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/redis_cache.py#L102-L105)

## debugging-05 (debugging)

Why does ModelConfig.validate_cache_dir reject a relative cache directory?

Reference: For a non-None value it checks os.path.isabs(v) and raises ModelConfigError saying the cache directory must be an absolute path when false.

Evidence:

- [app/core/config/model.py:151–152](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/core/config/model.py#L151-L152)
- [app/core/config/model.py:153–153](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/core/config/model.py#L153-L153)

## debugging-06 (debugging)

Why does check_drift return None even after the drift baseline has been established?

Reference: Disabled detection still returns None; with detection enabled and a baseline, fewer than min_samples current predictions also returns None.

Evidence:

- [app/services/drift_detection.py:259–265](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/drift_detection.py#L259-L265)

## changeimpact-01 (change-impact)

If APIKeyAuthMiddleware changed exempt-path startswith matching to exact equality, how would /docs/extra be treated when an API key is configured?

Reference: The exemption set contains /docs. The current prefix check exempts /docs/extra. Exact equality would remove that exemption, so the request would continue to the API-key checks (assuming it is not OPTIONS).

Evidence:

- [app/api/middleware/auth.py:49–49](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/middleware/auth.py#L49-L49)
- [app/api/middleware/auth.py:75–76](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/api/middleware/auth.py#L75-L76)

## changeimpact-02 (change-impact)

What changes in RedisCacheClient.set if its caller passes ttl=60 instead of ttl=None?

Reference: The same pickle-serialized value is sent to Redis with ex=60 rather than ex=None, requesting a 60-second expiration through the Redis client.

Evidence:

- [app/services/redis_cache.py:123–123](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/redis_cache.py#L123-L123)
- [app/services/redis_cache.py:124–125](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/redis_cache.py#L124-L125)

## changeimpact-03 (change-impact)

What factory cache behavior changes if backend is lowercased before constructing ModelFactory.create_model's cache_key?

Reference: The current key preserves backend casing, while backend selection already calls lower(). Normalizing the key would make otherwise identical ONNX and onnx calls address the same factory cache entry. This does not prove how many instances the backend getter itself creates.

Evidence:

- [app/models/factory.py:56–58](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/models/factory.py#L56-L58)
- [app/models/factory.py:59–61](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/models/factory.py#L59-L61)
- [app/models/factory.py:73–73](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/models/factory.py#L73-L73)
- [app/models/factory.py:74–74](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/models/factory.py#L74-L74)

## changeimpact-04 (change-impact)

For a direct PredictionService.predict call, what happens to text with surrounding spaces that makes len(text) exceed max_text_length, although stripped text would fit?

Reference: The current length check happens on raw text, so it raises TextTooLongError before the later model.predict(text.strip()). Moving that check after stripping could accept such input.

Evidence:

- [app/services/prediction.py:78–79](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L78-L79)
- [app/services/prediction.py:83–83](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/prediction.py#L83-L83)

## changeimpact-05 (change-impact)

What changes in dispatch_shadow_prediction when shadow_async_dispatch is set to false?

Reference: Instead of the background task branch, the else branch awaits _run_shadow_prediction, so dispatch waits for that coroutine to complete when shadow mode and the shadow model are enabled.

Evidence:

- [app/services/shadow_mode.py:185–185](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/shadow_mode.py#L185-L185)
- [app/services/shadow_mode.py:192–194](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/shadow_mode.py#L192-L194)

## changeimpact-06 (change-impact)

With a fixed pred_chi2_p, how does increasing ks_threshold affect prediction_drift_detected in check_drift?

Reference: The flag is pred_chi2_p < self.ks_threshold. A larger threshold can turn a previously false comparison true, and cannot turn a true one false for a fixed p-value.

Evidence:

- [app/services/drift_detection.py:327–328](https://github.com/arec1b0/KubeSentiment/blob/1aa3ebfd3f0467ea61142dff72d6534aa6968e20/app/services/drift_detection.py#L327-L328)
