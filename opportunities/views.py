"""Opportunities pages (templates/opportunities/):

    /opportunities/                  the board: Explore / Saved / Posted by me tabs,
                                     type chips, search, remote-only and sort
    /opportunities/new/              post one
    /opportunities/<id>/             details, Apply, save, share
    /opportunities/<id>/edit/        edit (the person who posted it)
    /opportunities/<id>/close/       close / reopen (POST, the poster)
    /opportunities/<id>/delete/      delete (POST, the poster)
    /opportunities/<id>/save/        save / unsave (POST, returns JSON for the bookmark)

Everything is scoped to the student's own university. Explore hides closed
ones (past deadline or marked closed) unless "Show closed" is ticked.
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import OpportunityForm
from .models import Opportunity, OpportunitySave

TABS = [('explore', 'Explore'), ('saved', 'Saved'), ('mine', 'Posted by me')]


def _university(request):
	student = getattr(request.user, 'student_profile', None)
	if student is None:
		raise Http404('Only students can use Opportunities.')
	return student.university


def open_filter():
	today = timezone.localdate()
	return Q(is_closed=False) & (Q(deadline__isnull=True) | Q(deadline__gte=today))


def _mine(request, pk):
	opp = get_object_or_404(Opportunity, pk=pk, university=_university(request))
	if opp.posted_by_id != request.user.pk:
		raise Http404
	return opp


@login_required
def board(request):
	uni = _university(request)
	tab = request.GET.get('tab', 'explore')
	if tab not in dict(TABS):
		tab = 'explore'
	kind = request.GET.get('kind', '')
	if kind not in dict(Opportunity.KIND_CHOICES):
		kind = ''
	q = ' '.join(request.GET.get('q', '').split())[:80]
	remote = request.GET.get('remote') == '1'
	show_closed = request.GET.get('closed') == '1'
	sort = request.GET.get('sort', 'new')

	qs = Opportunity.objects.filter(university=uni).select_related('posted_by')
	if tab == 'saved':
		qs = qs.filter(saves__user=request.user)
	elif tab == 'mine':
		qs = qs.filter(posted_by=request.user)
	elif not show_closed:
		qs = qs.filter(open_filter())
	if kind:
		qs = qs.filter(kind=kind)
	if remote:
		qs = qs.filter(is_remote=True)
	for word in q.split():
		qs = qs.filter(Q(title__icontains=word) | Q(organization__icontains=word) | Q(description__icontains=word)
			| Q(location__icontains=word) | Q(eligibility__icontains=word) | Q(kind__icontains=word.rstrip('s')))
	if sort == 'deadline':
		# Soonest deadline first; ones without a deadline last.
		from django.db.models import F
		qs = qs.order_by(F('deadline').asc(nulls_last=True), '-created_at')
	else:
		sort = 'new'
		qs = qs.order_by('-created_at')

	from feed.closeness import SECTION_PAGE, overview
	from . import discover
	open_now = Opportunity.objects.filter(university=uni).filter(open_filter())
	ctx = {'tab': tab, 'tabs': TABS, 'kind': kind, 'kinds': Opportunity.KIND_CHOICES, 'q': q,
		'remote': remote, 'show_closed': show_closed, 'sort': sort,
		'open_count': open_now.count(),
		'closing_soon': open_now.filter(deadline__isnull=False, deadline__lte=timezone.localdate() + timedelta(days=7)).count(),
		'see_all': ''.join(f'{k}={v}&' for k, v in (('kind', kind), ('remote', '1' if remote else ''),
			('closed', '1' if show_closed else ''), ('sort', sort if sort != 'new' else '')) if v)}
	student = getattr(request.user, 'student_profile', None)
	if tab == 'explore' and not q and student is not None:
		# Closest first, in sections of cards (opportunities/discover.py).
		parts = discover.sections(student, request.user, qs)
		one = next((p for p in parts if p[0] == request.GET.get('section')), None)
		if one is None:
			return render(request, 'opportunities/list.html', dict(ctx, groups=overview(parts),
				mine_count=Opportunity.objects.filter(university=uni, posted_by=request.user).count()))
		page = Paginator(one[3], SECTION_PAGE).get_page(request.GET.get('page'))
		return render(request, 'opportunities/list.html', dict(ctx, page=page, items=list(page),
			section={'key': one[0], 'title': one[1], 'sub': one[2]}, total=len(one[3])))
	page = Paginator(qs, SECTION_PAGE).get_page(request.GET.get('page'))
	return render(request, 'opportunities/list.html', dict(ctx, page=page, items=discover.prepare(page, request.user)))


@login_required
def detail(request, pk):
	opp = get_object_or_404(Opportunity.objects.select_related('posted_by', 'posted_by__student_profile'), pk=pk, university=_university(request))
	saved = OpportunitySave.objects.filter(user=request.user, opportunity=opp).exists()
	return render(request, 'opportunities/detail.html', {'opp': opp, 'saved': saved, 'save_count': opp.saves.count()})


@login_required
def create(request):
	uni = _university(request)
	form = OpportunityForm(request.POST or None)
	if request.method == 'POST' and form.is_valid():
		opp = form.save(commit=False)
		opp.university, opp.posted_by = uni, request.user
		opp.save()
		messages.success(request, 'Opportunity posted.')
		return redirect(opp)
	return render(request, 'opportunities/form.html', {'form': form, 'editing': False})


@login_required
def edit(request, pk):
	opp = _mine(request, pk)
	form = OpportunityForm(request.POST or None, instance=opp)
	if request.method == 'POST' and form.is_valid():
		form.save()
		messages.success(request, 'Opportunity updated.')
		return redirect(opp)
	return render(request, 'opportunities/form.html', {'form': form, 'editing': True, 'opp': opp})


@login_required
@require_POST
def toggle_closed(request, pk):
	opp = _mine(request, pk)
	opp.is_closed = not opp.is_closed
	opp.save(update_fields=['is_closed'])
	messages.success(request, 'Marked as closed.' if opp.is_closed else 'Reopened.')
	return redirect(opp)


@login_required
@require_POST
def delete(request, pk):
	opp = _mine(request, pk)
	opp.delete()
	messages.success(request, 'Opportunity deleted.')
	return redirect('opportunities')


@login_required
@require_POST
def toggle_save(request, pk):
	opp = get_object_or_404(Opportunity, pk=pk, university=_university(request))
	row = OpportunitySave.objects.filter(user=request.user, opportunity=opp)
	if row.exists():
		row.delete()
		saved = False
	else:
		OpportunitySave.objects.create(user=request.user, opportunity=opp)
		saved = True
	if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
		return JsonResponse({'saved': saved, 'count': opp.saves.count()})
	return redirect(request.META.get('HTTP_REFERER') or opp.get_absolute_url())
