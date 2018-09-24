import simpy


class BandwidthManager:
    # bandwidth_trace: list of tupel (time[s], bandwidth[B/s]), sorted by time
    def __init__(self, bandwidth_trace: list):
        # list of tupel (start time[s], end time[s], bandwidth[B/s]), sorted by time
        self.bandwidth_trace = self.create_bandwidth_trace(bandwidth_trace)

    @staticmethod
    def create_bandwidth_trace(bandwidth_trace: list):
        bandwidth = []
        for i in range(0, bandwidth_trace.__len__() - 1):
            bandwidth.append((bandwidth_trace[i][0], bandwidth_trace[i + 1][0], bandwidth_trace[i][1]))
        bandwidth.append((bandwidth_trace[-1][0], -1, bandwidth_trace[-1][1]))
        return bandwidth

    def get_download_time(self, time: float, byte_size: float):
        download_time = time
        for (start, end, bandwidth) in self.bandwidth_trace:
            if start <= download_time and end == -1:
                download_time += byte_size / bandwidth
                break
            elif start <= download_time <= end:
                max_interval_download = bandwidth * (end - download_time)
                if byte_size > max_interval_download:
                    byte_size -= max_interval_download
                    download_time = end
                else:
                    download_time += byte_size / bandwidth
                    break
        return download_time - time

    def get_average_bandwidth(self, start_time: float, end_time: float):
        average_bandwidth = 0
        for (start, end, bandwidth) in self.bandwidth_trace:
            if start < end_time and end == -1:
                average_bandwidth += bandwidth * (end_time - max(start, start_time))
                break
            else:
                interval_len = self.interval_len(start, end, start_time, end_time)
                average_bandwidth += bandwidth * interval_len
        return average_bandwidth / (end_time - start_time)

    @staticmethod
    def interval_len(i1_b, i1_e, i2_b, i2_e):
        interval_len = min((i1_e, i2_e)) - max((i1_b, i2_b))
        return interval_len if interval_len > 0 else 0
