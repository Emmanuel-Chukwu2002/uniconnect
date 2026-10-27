"""Per-student macro F1@5 for the Marketplace recommender, same signals and
weights as feed/recommender.py (content 0.4, department group 0.6, cf 0).

Protocol (stated, so it can be repeated): for each student with >= 4 distinct
listings touched, the latest 25% of those listings (by first touch) are held
out as "relevant"; everything earlier is training history.
Run from the project folder:  python notebooks/eval_f1.py ml_data
(needs requirements-ml.txt; writes ml_data/f1_results.json). Each method
recommends 5 listings the student has not touched in training, not their own,
available only. P, R and F1 are computed per student, then averaged.
"""
import json
import sys
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

D = sys.argv[1]
K = 5
W = {'cf': 0.0, 'content': 0.4, 'group': 0.6}
inter = pd.read_csv(f'{D}/interactions.csv')
lst = pd.read_csv(f'{D}/listings.csv')
usr = pd.read_csv(f'{D}/users.csv')
inter = inter[inter.item_type == 'listing'].copy()
inter['ts'] = pd.to_datetime(inter.timestamp, utc=True, format='ISO8601')

items = lst.listing_id.values
ix = {i: n for n, i in enumerate(items)}
avail = (lst.status == 'available').values
seller = lst.seller_id.values
text = (lst.title + ' ' + lst.description.fillna('') + ' ' + lst.category + ' ' + lst.condition).values
X = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), sublinear_tf=True).fit_transform(text)
grp = dict(zip(usr.user_id, usr.group))

inter = inter[inter.item_id.isin(ix)]
first = inter.groupby(['user_id', 'item_id']).ts.min().reset_index()
cnt = first.groupby('user_id').size()
users = [u for u in cnt.index if cnt[u] >= 4 and u in grp]

train_rows, test = [], {}
for u in users:
    f = first[first.user_id == u].sort_values('ts')
    n_test = max(1, int(round(0.25 * len(f))))
    test[u] = set(f.item_id.values[-n_test:])
    keep = set(f.item_id.values[:-n_test])
    train_rows.append(inter[(inter.user_id == u) & inter.item_id.isin(keep)])
train = pd.concat(train_rows)
uix = {u: n for n, u in enumerate(users)}
w = train.action.map({'view': 1.0, 'cart': 5.0}).fillna(1.0)
M = csr_matrix((w.values, (train.user_id.map(uix).values, train.item_id.map(ix).values)), shape=(len(users), len(items)))
M.sum_duplicates()
groups = np.array([grp[u] for u in users])
gpop = {g: np.asarray(M[groups == g].sum(axis=0)).ravel() for g in set(groups)}
overall = np.asarray(M.sum(axis=0)).ravel()
S = cosine_similarity(M.T, dense_output=False)


def mm(s):
    lo, hi = s.min(), s.max()
    return (s - lo) / (hi - lo) if hi > lo else np.zeros_like(s)


def prf(rec, rel):
    hit = len(set(rec) & rel)
    p, r = hit / K, hit / len(rel)
    return p, r, (2 * p * r / (p + r) if hit else 0.0)


def top(score, u, seen):
    ok = avail & (seller != users[u])
    ok[list(seen)] = False
    order = np.argsort(-np.where(ok, score, -np.inf), kind='stable')
    return [items[j] for j in order[:K] if ok[j]]


methods = {k: [] for k in ['Random', 'Most popular', 'Popular in dept group', 'Item-item CF', 'Content (TF-IDF)', 'Hybrid (app)']}
rng = np.random.default_rng(0)
for u, user in enumerate(users):
    seen = set(M[u].indices)
    rel = test[user]
    gp = gpop[groups[u]] if gpop[groups[u]].any() else overall
    prof = normalize(M[u] @ X)
    content = (X @ prof.T).toarray().ravel()
    cf = (M[u] @ S).toarray().ravel()
    scores = {
        'Random': rng.random(len(items)),
        'Most popular': overall,
        'Popular in dept group': gp,
        'Item-item CF': cf,
        'Content (TF-IDF)': content,
        'Hybrid (app)': W['group'] * mm(gp) + W['content'] * mm(content),
    }
    for name, sc in scores.items():
        methods[name].append(prf(top(sc, u, seen), rel))

out = {}
print(f'students evaluated: {len(users)}  held-out items per student (mean): {np.mean([len(t) for t in test.values()]):.2f}  catalogue: {len(items)}')
print(f'{"method":26s} {"P@5":>7s} {"R@5":>7s} {"F1@5 (macro)":>13s}  {"F1 of means":>11s}')
for name, rows in methods.items():
    a = np.array(rows)
    p, r, f = a.mean(0)
    fm = 2 * p * r / (p + r) if p + r else 0
    out[name] = dict(precision=round(p, 4), recall=round(r, 4), f1_macro=round(f, 4), f1_of_means=round(fm, 4))
    print(f'{name:26s} {p:7.4f} {r:7.4f} {f:13.4f}  {fm:11.4f}')

# paired bootstrap: hybrid vs dept-group, per-student F1
h = np.array(methods['Hybrid (app)'])[:, 2]
g = np.array(methods['Popular in dept group'])[:, 2]
b = [np.mean((h - g)[rng.integers(0, len(h), len(h))]) for _ in range(5000)]
lo, hi = np.percentile(b, [2.5, 97.5])
print(f'\nHybrid minus dept-group F1: {np.mean(h-g):+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]')
hb = [np.mean(h[rng.integers(0, len(h), len(h))]) for _ in range(5000)]
print(f'Hybrid F1 95% CI: [{np.percentile(hb,2.5):.4f}, {np.percentile(hb,97.5):.4f}]')
json.dump({'protocol': 'latest 25% of each student\'s touched listings held out; top-5 new available listings; per-student P/R/F1 averaged',
           'students': len(users), 'results': out}, open(f'{D}/f1_results.json', 'w'), indent=1)
