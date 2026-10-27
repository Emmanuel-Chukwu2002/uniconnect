"""Small server-drawn SVG charts for the dashboard (no JavaScript library needed).
Colours come from CSS classes (static/css/admin.css), so both themes work."""
import math

from django.utils.html import escape
from django.utils.safestring import mark_safe

W, H = 440, 210
L, R, T, B = 40, 12, 14, 30      # padding: left (y labels), right, top, bottom (x labels)


def _nice_max(v):
	"""A top value that splits into 4 round steps (0, 25, 50, 75, 100)."""
	if v <= 4:
		return 4
	raw = v / 4
	exp = 10 ** int(math.floor(math.log10(raw)))
	for m in (1, 2, 2.5, 5, 10):
		if m * exp >= raw and (m * exp) == int(m * exp):
			return int(m * exp) * 4
	return int(10 * exp) * 4


def _fmt(v):
	return f'{v:,.0f}' if v == int(v) else f'{v:,.1f}'


def _frame(top):
	parts = []
	for i in range(5):
		val = top * i / 4
		y = T + (H - T - B) * (1 - i / 4)
		parts.append(f'<line class="ch-grid" x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}"/>')
		parts.append(f'<text class="ch-ylab" x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{_fmt(val)}</text>')
	return parts


def _xlabels(labels, xs):
	step = max(1, math.ceil(len(labels) / 8))
	return [f'<text class="ch-xlab" x="{x:.1f}" y="{H - 8}" text-anchor="middle">{escape(lab)}</text>'
		for i, (lab, x) in enumerate(zip(labels, xs)) if i % step == 0 or i == len(labels) - 1]


def line_chart(labels, values, title=''):
	top = _nice_max(max(values) if values else 0)
	n = len(values)
	xs = [L + 14 + (W - L - R - 28) * (i / (n - 1) if n > 1 else 0.5) for i in range(n)]
	ys = [T + (H - T - B) * (1 - v / top) for v in values]
	parts = _frame(top)
	if n:
		pts = ' '.join(f'{x:.1f},{y:.1f}' for x, y in zip(xs, ys))
		base = H - B
		parts.append(f'<polygon class="ch-area" points="{xs[0]:.1f},{base} {pts} {xs[-1]:.1f},{base}"/>')
		parts.append(f'<polyline class="ch-line" points="{pts}"/>')
		for x, y, v, lab in zip(xs, ys, values, labels):
			parts.append(f'<circle class="ch-dot" cx="{x:.1f}" cy="{y:.1f}" r="3.5"><title>{escape(lab)}: {v}</title></circle>')
	parts += _xlabels(labels, xs)
	return mark_safe(f'<svg viewBox="0 0 {W} {H}" class="ch" role="img" aria-label="{escape(title)}">{"".join(parts)}</svg>')


def bar_chart(labels, groups, title=''):
	"""groups: {series name: [values]} drawn side by side; series get classes ch-s0, ch-s1, ..."""
	names = list(groups)
	allv = [v for vals in groups.values() for v in vals]
	top = _nice_max(max(allv) if allv else 0)
	n = len(labels)
	slot = (W - L - R) / max(n, 1)
	bw = min(14, slot * 0.8 / max(len(names), 1))
	parts = _frame(top)
	xs = []
	for i in range(n):
		cx = L + slot * (i + 0.5)
		xs.append(cx)
		x0 = cx - bw * len(names) / 2
		for j, name in enumerate(names):
			v = groups[name][i]
			h = (H - T - B) * v / top
			parts.append(f'<rect class="ch-s{j}" x="{x0 + j * bw:.1f}" y="{H - B - h:.1f}" width="{bw - 2:.1f}" height="{h:.1f}" rx="2">'
				f'<title>{escape(labels[i])} · {escape(name)}: {v}</title></rect>')
	parts += _xlabels(labels, xs)
	return mark_safe(f'<svg viewBox="0 0 {W} {H}" class="ch" role="img" aria-label="{escape(title)}">{"".join(parts)}</svg>')
