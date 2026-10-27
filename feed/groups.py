"""Department groups, shared by the simulated-data generator, the data
export and the recommender.

A department's group (tech, engineering, science, arts, social, law) is
how the recommender recognises that, say, Electrical and Mechanical
Engineering students tend to want similar things.
"""

# First keyword match wins, so the broad "science" keyword comes last:
# "Political Science" is social and "Computer Science" is tech, not science.
GROUP_KEYWORDS = [
	('tech', ['computer', 'software', 'information', 'cyber', 'data']),
	('engineering', ['engineering']),
	('law', ['law']),
	('social', ['economics', 'political', 'sociology', 'psychology', 'accounting', 'business', 'mass comm']),
	('arts', ['english', 'history', 'language', 'literature', 'philosophy', 'music', 'theatre', 'art']),
	('science', ['math', 'physics', 'chemistry', 'biology', 'statistics', 'science']),
]

# How each group reads in a sentence: "Popular with engineering students".
GROUP_LABELS = {
	'tech': 'computing', 'engineering': 'engineering', 'science': 'science',
	'arts': 'arts', 'social': 'social science', 'law': 'law', 'general': 'other',
}


def department_group(department_name):
	name = (department_name or '').lower()
	for group, keywords in GROUP_KEYWORDS:
		if any(word in name for word in keywords):
			return group
	return 'general'
