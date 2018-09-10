from numpy import linspace

from seminar.buffer import Buffer


class Name:
    def __init__(self, buffer: Buffer, representation_byte_rates, b_min, b_low, b_high):
        # safety margins, values used by the paper
        self.a = [0.75, 0.33, 0.5, 0.75, 0.9]
        self.delta_beta = 1
        self.delta_t = 10

        self.b_min = b_min
        self.b_low = b_low
        self.b_high = b_high
        self.b_opt = (self.b_low + self.b_high) * 0.5

        self.r = representation_byte_rates
        self.r_min = 0
        self.r_max = self.r.__len__() - 1

        self.running_fast_start = True

        self.buffer = buffer

    def get(self):
        start, t, segment = self.buffer.downloaded_segments[-1]
        b_delay = 0
        r_next = segment.representation

        r_n = segment.representation
        buffer_level = self.buffer_level(t)
        average_throughput = self.average_throughput(t - self.delta_t, t)

        if self.running_fast_start \
                and r_n != self.r_max\
                and self.monoton(t) \
                and self.r[r_n] <= self.a[0] * average_throughput:
            if buffer_level < self.b_min:
                if self.r[r_n + 1] <= self.a[1] * average_throughput:
                    r_next = r_n + 1
            elif buffer_level < self.b_low:
                if self.r[r_n + 1] <= self.a[2] * average_throughput:
                    r_next = r_n + 1
            else:
                if self.r[r_n + 1] <= self.a[3] * average_throughput:
                    r_next = r_n + 1
                if buffer_level > self.b_high:
                    b_delay = self.b_high - segment.duration
        else:
            self.running_fast_start = False
            if buffer_level < self.b_min:
                r_next = self.r_min
            elif buffer_level < self.b_low:
                if r_n != self.r_min and self.r[r_n] >= self.segment_throughput(segment.segment_index):
                    r_next = r_n - 1
            elif buffer_level < self.b_high:
                if r_n == self.r_max or self.r[r_n + 1] >= self.a[4] * average_throughput:
                    b_delay = max(buffer_level - segment.duration, self.b_opt)
            else:
                if r_n == self.r_max or self.r[r_n + 1] >= self.a[4] * average_throughput:
                    b_delay = max(buffer_level - segment.duration, self.b_opt)
                else:
                    r_next = r_n + 1
        # we return max wait time instead of b_delay
        # print(buffer_level, b_delay)
        return r_next, b_delay if b_delay == 0 else max(buffer_level - b_delay, 0)

    def monoton(self, time):
        steps = 10
        tmp = [self.buffer_level(i) for i in linspace(0, time, steps, endpoint=True)]
        for i in range(0, steps - 1):
            if tmp[i] > tmp[i + 1]:
                return False
        return True

    def segment_throughput(self, index):
        start, end, segment = self.buffer.downloaded_segments[index]
        return (segment.__len__()) / (end - start)

    # byte / second
    def average_throughput(self, t1, t2):
        segments = self.buffer.downloaded_segments
        n = 0
        for (start, end, segment) in segments:
            if end <= t2:
                n += 1
        sum_a = 0
        sum_b = 0
        for i in range(0, n):
            start, end, segment = self.buffer.downloaded_segments[i]
            interval_len = self.interval_len(start, end, t1, t2)
            sum_a += self.segment_throughput(i) * interval_len
            sum_b += interval_len
        return sum_a / sum_b

    @staticmethod
    def interval_len(i1_b, i1_e, i2_b, i2_e):
        interval_len = min((i1_e, i2_e)) - max((i1_b, i2_b))
        return interval_len if interval_len > 0 else 0

    def buffer_level(self, time: float) -> float:
        return self.buffer.buffer_level(time)

    def min_buffer_level(self, time: float) -> float:
        lower = int(time / self.delta_beta) * self.delta_beta
        upper = lower + self.delta_beta
        return min([self.buffer_level(i) for i in range(lower, upper + 1)])
