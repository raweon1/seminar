from numpy import linspace

from seminar.bandwidth import BandwidthManager
from seminar.buffer import Buffer


class DualAdaption:
    # representation_byte_rates, b_min, b_low, b_high
    def __init__(self, bandwidth_manager: BandwidthManager, buffer, short_factor, short_param, long_param):
        self.a = [0.85, 0.85, 0.85, 0.75, 0.9]
        self.delta_beta = 1
        self.delta_t = 5

        self.bandwidth_manager = bandwidth_manager

        self.short_factor = short_factor
        self.short_param = short_param
        self.long_param = long_param

        self.running_fast_start_short = True
        self.running_fast_start_long = True

        self.buffer = buffer

        self.short = []
        self.long = []

    def get_short(self, index, time):
        # last downloaded segment (download short) for representation
        segment, download = self.buffer.short_segments[index]
        buffer_level = self.buffer.buffer_level_short(time)
        monoton = self.monoton_short(time)
        self.short.append((time, buffer_level))
        r_next, b_delay, running_fast_start = self.get(time, download, self.short_factor, buffer_level, monoton,
                                                       self.running_fast_start_short, self.short_param["r"],
                                                       self.short_param["r_max"], self.short_param["r_min"],
                                                       self.short_param["b_min"],
                                                       self.short_param["b_low"], self.short_param["b_high"])
        self.running_fast_start_short = running_fast_start
        return r_next, b_delay

    def get_long(self, index, time):
        segment, download = self.buffer.long_segments[index]
        buffer_level = self.buffer.buffer_level(time)
        monoton = self.monoton_long(time)
        self.long.append((time, buffer_level))
        r_next, b_delay, running_fast_start = self.get(time, download, 1 - self.short_factor, buffer_level, monoton,
                                                       self.running_fast_start_long, self.long_param["r"],
                                                       self.long_param["r_max"], self.long_param["r_min"],
                                                       self.long_param["b_min"],
                                                       self.long_param["b_low"], self.long_param["b_high"])
        self.running_fast_start_long = running_fast_start
        return r_next, b_delay

    def get(self, time, download, bandwidth_factor, buffer_level, monoton, running_fast_start, r, r_max, r_min, b_min,
            b_low, b_high):
        b_opt = (b_low + b_high) * 0.5
        t = time
        b_delay = 0
        segment = download.segment
        r_next = segment.representation

        r_n = segment.representation
        average_throughput = self.bandwidth_manager.get_average_bandwidth(t - self.delta_t, t) * bandwidth_factor
        segment_throughput = self.bandwidth_manager.get_average_bandwidth(t - segment.duration, t) * bandwidth_factor
        if running_fast_start \
                and r_n != r_max \
                and monoton \
                and r[r_n] <= self.a[0] * average_throughput:
            if buffer_level < b_min:
                if r[r_n + 1] <= self.a[1] * average_throughput:
                    r_next = r_n + 1
            elif buffer_level < b_low:
                if r[r_n + 1] <= self.a[2] * average_throughput:
                    r_next = r_n + 1
            else:
                if r[r_n + 1] <= self.a[3] * average_throughput:
                    r_next = r_n + 1
                if buffer_level > b_high:
                    b_delay = b_high - segment.duration
        else:
            running_fast_start = False
            if buffer_level < b_min:
                r_next = r_min
            elif buffer_level < b_low:
                if r_n != r_min and r[r_n] >= segment_throughput:
                    r_next = r_n - 1
            elif buffer_level < b_high:
                if r_n == r_max or r[r_n + 1] >= self.a[4] * average_throughput:
                    b_delay = max(buffer_level - segment.duration, b_opt)
            else:
                if r_n == r_max or r[r_n + 1] >= self.a[4] * average_throughput:
                    b_delay = max(buffer_level - segment.duration, b_opt)
                else:
                    while r_next < r_max and r[r_next + 1] <= self.a[4] * average_throughput:
                        r_next += 1
                    b_delay = max(buffer_level - segment.duration, b_opt)
        # we return max wait time instead of b_delay
        # print(buffer_level, b_delay)
        return r_next, b_delay if b_delay == 0 else max(buffer_level - b_delay, 0), running_fast_start

    def monoton_short(self, time):
        steps = 10
        tmp = [self.buffer.buffer_level_short(i) for i in linspace(0, time, steps, endpoint=True)]
        for i in range(0, steps - 1):
            if tmp[i] > tmp[i + 1]:
                return False
        return True

    def monoton_long(self, time):
        steps = 10
        tmp = [self.buffer.buffer_level(i) for i in linspace(0, time, steps, endpoint=True)]
        for i in range(0, steps - 1):
            if tmp[i] > tmp[i + 1]:
                return False
        return True


class Name:
    def __init__(self, buffer: Buffer, representation_byte_rates, b_min, b_low, b_high):
        # safety margins, values used by the paper
        self.a = [0.75, 0.33, 0.5, 0.75, 0.9, 1]
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
                and r_n != self.r_max \
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
                if r_n != self.r_min and self.r[r_n] >= self.segment_throughput(segment.segment_index) * self.a[5]:
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
