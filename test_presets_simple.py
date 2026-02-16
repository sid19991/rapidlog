from rapidlog import get_logger

# Test low-memory preset
logger = get_logger(preset="low-memory")
logger.info("test from low-memory", value=1)
logger.close()
print("✓ low-memory preset works")

# Test throughput preset
logger = get_logger(preset="throughput")
logger.info("test from throughput", value=2)
logger.close()
print("✓ throughput preset works")

# Test balanced (default) preset
logger = get_logger(preset="balanced")
logger.info("test from balanced", value=3)
logger.close()
print("✓ balanced preset works")

print("\nAll presets working correctly!")
