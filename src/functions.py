
# https://www.statology.org/normalize-data-between-0-and-100/

def normalize(value, min_value, max_value, min_normalized, max_normalized):
	if value < min_value or value > max_value:
		raise ValueError("Value out of range")
	return round(((value - min_value) / (max_value - min_value)) * (max_normalized - min_normalized) + min_normalized)
