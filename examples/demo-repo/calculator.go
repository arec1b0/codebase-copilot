package calculator

// Add returns the sum of two integers.
func Add(left int, right int) int {
    return left + right
}

type Counter struct {
    Value int
}

func (counter *Counter) Increment(amount int) int {
    counter.Value += amount
    return counter.Value
}
