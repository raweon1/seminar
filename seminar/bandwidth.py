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
        download_time = 0
        for (start, end, bandwidth) in self.bandwidth_trace:
            if end == -1:
                download_time += byte_size / bandwidth
                return download_time
            elif start <= time + download_time < end:
                download = (end - (time + download_time)) * bandwidth
                if byte_size < download:
                    download_time += byte_size / bandwidth
                    return download_time
                else:
                    download_time += end - (time + download_time)
                    byte_size -= download
        return download_time
