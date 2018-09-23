from seminar.bandwidth import BandwidthManager

bandwidth = 781250
bandwidth_trace = [(0, bandwidth), (70, 0), (85, bandwidth / 2)]

bandwidth_manager = BandwidthManager(bandwidth_trace)

print(bandwidth_manager.get_average_bandwidth(0, 70) == bandwidth)
print(bandwidth_manager.get_average_bandwidth(65, 75) == bandwidth / 2)
print(bandwidth_manager.get_average_bandwidth(70, 85) == 0)
print(bandwidth_manager.get_average_bandwidth(80, 90) == bandwidth / 4)

print(bandwidth_manager.get_download_time(0, bandwidth * 5) == 5)
print(bandwidth_manager.get_download_time(65, bandwidth * 5) == 5)
print(bandwidth_manager.get_download_time(66, bandwidth * 5) == 21)
print(bandwidth_manager.get_download_time(80, bandwidth * 5) == 15)
print(bandwidth_manager.get_download_time(500, bandwidth * 5) == 10)
