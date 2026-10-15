int add(int left, int right) {
    return left + right;
}

class Counter {
public:
    int increment(int amount = 1) {
        value_ += amount;
        return value_;
    }

private:
    int value_ = 0;
};
