"""UniConnect's Marketplace recommender: the model evaluated in
notebooks/recommender.ipynb, packaged for the app.

What it does, in order:

  1. Builds an "implicit rating" for every (student, listing) pair from the
     Interaction log: the sum of action weights (view = 1, add to cart = 5).
  2. Scores every listing for every student with up to three signals:
       content   TF-IDF similarity between the listing's text and the text
                 of listings the student has engaged with
       group     how popular the listing is among students in the same
                 department group (tech, engineering, law, ...)
       cf        item-item collaborative filtering ("students who liked
                 this also liked that")
  3. Rescales each signal to 0-1 per student and blends them with the weights
     tuned in the notebook (ml_data/recommender_settings.json).
  4. Keeps the top k listings that are available, not the student's own, and
     "new products only": nothing they've already interacted with, not even
     another seller's copy of the same product.
  5. Attaches a one-line reason to each recommendation, based on which
     signal actually contributed most to that listing's score.

numpy/scipy/scikit-learn are imported inside the functions, so the web app
itself never needs them — only `python manage.py train_recommender` does.
"""
import json
from pathlib import Path

from django.conf import settings

from .groups import GROUP_LABELS, department_group

DEFAULT_SETTINGS = {
	'k': 5,
	'weights': {'cf': 0.0, 'content': 0.4, 'group': 0.6},
	'tfidf': {'stop_words': 'english', 'ngram_range': [1, 2], 'sublinear_tf': True},
}
SETTINGS_PATH = Path(settings.BASE_DIR) / 'ml_data' / 'recommender_settings.json'



def load_settings():
	"""The weights tuned in the notebook, or the defaults if the notebook
	hasn't been run on this machine."""
	if SETTINGS_PATH.exists():
		saved = json.loads(SETTINGS_PATH.read_text())
		return {**DEFAULT_SETTINGS, **{key: saved[key] for key in DEFAULT_SETTINGS if key in saved}}
	return DEFAULT_SETTINGS


def build_recommendations(k=None):
	"""Returns ({user_id: [(listing_id, score, reason), ...]}, info dict)."""
	import numpy as np
	from scipy.sparse import csr_matrix
	from sklearn.feature_extraction.text import TfidfVectorizer
	from sklearn.metrics.pairwise import cosine_similarity
	from sklearn.preprocessing import normalize

	from accounts.models import StudentProfile
	from .models import Interaction, Listing

	config = load_settings()
	k = k or config['k']
	weights = config['weights']

	# ---- Items: every listing (sold ones still describe people's taste).
	listings = list(Listing.objects.values('id', 'title', 'description', 'category', 'condition', 'status', 'seller_id'))
	if not listings:
		return {}, {'reason': 'no listings'}
	item_ids = np.array([l['id'] for l in listings])
	item_index = {item: i for i, item in enumerate(item_ids)}
	titles = np.array([l['title'] for l in listings], dtype=object)
	sellers = np.array([l['seller_id'] for l in listings])
	available = np.array([l['status'] == Listing.STATUS_AVAILABLE for l in listings])

	# ---- Users: every student, including ones with no activity yet.
	profiles = list(StudentProfile.objects.values('user_id', 'department__name'))
	user_ids = np.array([p['user_id'] for p in profiles])
	user_index = {user: i for i, user in enumerate(user_ids)}
	groups = np.array([department_group(p['department__name']) for p in profiles], dtype=object)

	# ---- Step 1: implicit ratings matrix (students x listings).
	rows, cols, vals = [], [], []
	for user_id, item_id, action in (Interaction.objects
			.filter(item_type=Interaction.ITEM_LISTING)
			.values_list('user_id', 'item_id', 'action')):
		if user_id in user_index and item_id in item_index:
			rows.append(user_index[user_id])
			cols.append(item_index[item_id])
			vals.append(Interaction.ACTION_WEIGHTS.get(action, 1.0))
	M = csr_matrix((vals, (rows, cols)), shape=(len(user_ids), len(item_ids)))
	M.sum_duplicates()  # several actions on one listing add up

	# ---- Step 2: the three signals.
	text = [f"{l['title']} {l['description'] or ''} {l['category']} {l['condition']}" for l in listings]
	tfidf_options = dict(config['tfidf'])
	tfidf_options['ngram_range'] = tuple(tfidf_options['ngram_range'])
	X = TfidfVectorizer(**tfidf_options).fit_transform(text)
	# For explanations only: titles + category, so "Because you viewed X"
	# names a genuinely similar item, not one that merely shares stock
	# phrases like "pick-up on campus" in its description.
	R = TfidfVectorizer(stop_words='english').fit_transform([f"{l['title']} {l['category']}" for l in listings])

	group_popularity = {g: np.asarray(M[groups == g].sum(axis=0)).ravel() for g in set(groups)}
	overall_popularity = np.asarray(M.sum(axis=0)).ravel()
	item_similarity = cosine_similarity(M.T, dense_output=False) if weights.get('cf') else None

	def minmax(scores):
		lo, hi = scores.min(), scores.max()
		return (scores - lo) / (hi - lo) if hi > lo else np.zeros_like(scores)

	recommendations = {}
	for u, user_id in enumerate(user_ids):
		history = M[u].indices
		popular_reason = f"Popular with {GROUP_LABELS.get(groups[u], 'other')} students"
		signals = {'group': group_popularity[groups[u]]}
		if not signals['group'].any():
			# Nobody in this student's group has done anything yet: fall back
			# to what's popular with everyone, and say so honestly.
			signals['group'] = overall_popularity
			popular_reason = 'Popular on the Marketplace'
		if len(history):
			profile = normalize(M[u] @ X)
			signals['content'] = (X @ profile.T).toarray().ravel()
			if item_similarity is not None:
				signals['cf'] = (M[u] @ item_similarity).toarray().ravel()
		# Step 3: blend.
		parts = {name: weights.get(name, 0) * minmax(values) for name, values in signals.items()}
		score = sum(parts.values())
		if np.isscalar(score) or not np.any(score):  # nothing to go on at all
			continue

		# Step 4: pick the top k, new products only.
		seen_titles = set(titles[history])
		allowed = available & (sellers != user_id)
		picked = []
		for j in np.argsort(-score, kind='stable'):
			if not allowed[j] or titles[j] in seen_titles:
				continue
			picked.append(j)
			seen_titles.add(titles[j])  # one listing per product
			if len(picked) == k:
				break

		# Step 5: a reason for each — whichever signal contributed more.
		results = []
		for j in picked:
			reason = popular_reason
			personal = parts.get('content', 0)[j] if 'content' in parts else 0
			personal += parts['cf'][j] if 'cf' in parts else 0
			if personal > parts['group'][j]:
				similarity = (R[history] @ R[j].T).toarray().ravel()
				if similarity.max() > 0:
					closest = titles[history[similarity.argmax()]]
					reason = f'Because you viewed "{closest[:120]}"'
			results.append((int(item_ids[j]), float(score[j]), reason))
		if results:
			recommendations[int(user_id)] = results

	info = {
		'students': len(user_ids), 'listings': len(item_ids), 'ratings': M.nnz,
		'weights': weights, 'k': k, 'settings_file': str(SETTINGS_PATH) if SETTINGS_PATH.exists() else 'defaults',
	}
	return recommendations, info
