const draftId = location.pathname.split('/').filter(Boolean).pop();

const el = {
	title: document.getElementById('title'),
	step: document.getElementById('step'),
	log: document.getElementById('log'),
	options: document.getElementById('options'),
	notice: document.getElementById('notice'),
	confirmBar: document.getElementById('confirm-bar'),
	top: document.getElementById('top'),
};

let sending = false;

let selection = null;

function element(tag, className, text) {
	const node = document.createElement(tag);
	if (className) node.className = className;
	if (text !== undefined) node.textContent = text;
	return node;
}

function notify(text, kind = 'error') {
	clearTimeout(notify.timer);

	el.notice.textContent = text;
	el.notice.className = kind;
	el.notice.hidden = !text;

	if (text) notify.timer = setTimeout(() => { el.notice.hidden = true; }, 5000);
}

function chip(item, struck = false) {
	const node = element('span', struck ? 'chip struck' : 'chip');

	if (item.img) {
		const img = element('img');
		img.src = item.img;
		img.alt = '';
		img.loading = 'lazy';
		node.append(img);
	}

	node.append(element('span', 'chip-name', item.name));
	return node;
}

function sideBlock(view, side) {
	const data = view.sides[side];
	const block = element('div', `side ${side}`);

	const header = element('h2');
	header.append(element('span', 'dot'));
	header.append(element('span', 'who', view.names[side]));
	header.append(element('span', 'role', side === 'host' ? 'Host' : 'Guest'));
	if (view.turn === side) header.append(element('span', 'now', 'playing'));
	block.append(header);

	const setups = element('ol', 'setups');
	for (let n = 1; n <= 7; n += 1) {
		const setup = data.setups.find(s => s.n === n);
		const row = element('li', setup ? 'setup' : 'setup empty');

		if (!setup) {
			row.append(element('span', 'waiting', '—'));
		} else {
			row.append(chip(setup.turret));
			row.append(chip(setup.hull));
			row.append(setup.paint ? chip(setup.paint) : element('span', 'waiting', 'no paint'));
		}

		setups.append(row);
	}
	block.append(setups);

	const bans = element('div', 'bans');
	bans.append(element('h3', null, `Banned (${data.bans.length})`));

	if (data.bans.length === 0) {
		bans.append(element('p', 'waiting', 'no bans yet'));
	} else {
		const list = element('div', 'chips');
		for (const item of data.bans) list.append(chip(item, true));
		bans.append(list);
	}
	block.append(bans);

	return block;
}

function renderLog(view) {
	el.log.replaceChildren();
	el.log.append(sideBlock(view, 'host'));
	el.log.append(sideBlock(view, 'guest'));

	const history = element('div', 'history');
	history.append(element('h3', null, 'History'));

	if (view.history.length === 0) {
		history.append(element('p', 'waiting', 'the draft has not started yet'));
	} else {
		const list = element('ul');
		for (const line of view.history) {
			const li = element('li', line.side);
			li.append(element('span', 'step-num', `${line.step}`));
			li.append(element('span', null, line.text));
			list.append(li);
		}
		history.append(list);
	}

	el.log.append(history);
}

async function play(itemId, button) {
	if (sending) return;

	sending = true;
	button.classList.add('sending');

	try {
		const response = await fetch(`/api/draft/${draftId}/move`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ item: itemId }),
		});

		if (!response.ok) {
			const { error } = await response.json().catch(() => ({}));
			notify(error || `Could not send (${response.status}).`);
		}
	} catch {
		notify('No connection to the server.');
	} finally {
		sending = false;
		button.classList.remove('sending');
	}
}

function clearSelection() {
	selection = null;

	el.confirmBar.replaceChildren();
	el.confirmBar.hidden = true;
	document.body.classList.remove('has-selection');

	for (const node of el.options.querySelectorAll('.card.selected')) {
		node.classList.remove('selected');
		node.setAttribute('aria-pressed', 'false');
	}
}

function confirmSelection() {
	if (!selection) return;

	const { item, node } = selection;
	clearSelection();
	play(item.id, node);
}

function select(item, node, title) {
	if (sending) return;

	clearSelection();
	selection = { item, node };

	node.classList.add('selected');
	node.setAttribute('aria-pressed', 'true');

	const bar = element('div', 'bar');

	const target = element('div', 'target');
	target.append(Object.assign(new Image(), { src: item.img, alt: '' }));

	const text = element('div', 'text');
	text.append(element('strong', null, item.name));
	text.append(element('span', 'hint', title));
	target.append(text);

	const ok = element('button', 'confirm');
	ok.type = 'button';
	ok.append(element('span', 'box', '✓'));
	ok.append(document.createTextNode('Confirm'));
	ok.addEventListener('click', confirmSelection);

	const cancel = element('button', 'cancel', 'Cancel');
	cancel.type = 'button';
	cancel.addEventListener('click', clearSelection);

	bar.append(target, ok, cancel);

	el.confirmBar.replaceChildren(bar);
	el.confirmBar.hidden = false;
	document.body.classList.add('has-selection');

	ok.focus();
}

document.addEventListener('keydown', event => {
	if (event.key === 'Escape') clearSelection();
});

const CATEGORY_TITLE = { turret: 'Turrets', hull: 'Hulls', paint: 'Paints' };

function card(item, first, title) {
	const node = element(item.playable ? 'button' : 'div', 'card');

	if (item.banned) node.classList.add('banned');
	if (!item.playable) node.classList.add('locked');

	const loading = first ? 'eager' : 'lazy';
	const priority = first ? 'high' : 'auto';

	const img = Object.assign(new Image(), { src: item.img, alt: '', loading });
	img.fetchPriority = priority;

	node.append(img);
	node.append(element('span', 'name', item.name));

	if (item.playable) {
		node.type = 'button';
		node.setAttribute('aria-pressed', 'false');

		node.addEventListener('click', () => select(item, node, title));
		node.addEventListener('dblclick', () => {
			selection = { item, node };
			confirmSelection();
		});
	}

	return node;
}

function section(kind, items, active, firstOnScreen, title) {
	const block = element('section', active ? 'category active' : 'category');

	const header = element('h3');
	header.append(element('span', 'category-name', CATEGORY_TITLE[kind]));

	const playable = items.filter(item => item.playable).length;
	header.append(element('span', 'count', active ? `${playable} available` : `${items.length}`));

	block.append(header);

	const grid = element('div', 'grid');
	items.forEach((item, i) => grid.append(card(item, firstOnScreen && i === 0, title)));
	block.append(grid);

	return block;
}

function renderOptions(view) {
	el.options.replaceChildren();

	clearSelection();

	if (view.finished) {
		el.options.append(element('p', 'end', view.status === 'completed'
			? 'All 14 setups are locked in. The result is in the Discord channel.'
			: 'This draft was cancelled.'));
		return;
	}

	const header = element('div', 'options-header');

	header.append(element('h2', null, view.choice
		? view.choice.title
		: `${view.turn === 'host' ? 'Host' : 'Guest'}'s turn`));

	if (!view.choice) {
		header.append(element('span', 'count', 'waiting'));
	}

	el.options.append(header);

	if (view.choice?.pendingTurret) {
		const pending = element('p', 'pending');
		pending.append(document.createTextNode('Turret picked: '));
		pending.append(element('strong', null, view.choice.pendingTurret.name));
		pending.append(document.createTextNode(' — now the hull.'));
		el.options.append(pending);
	}

	for (const [i, kind] of ['turret', 'hull', 'paint'].entries()) {
		el.options.append(section(
			kind,
			view.grid[kind],
			view.choice?.category === kind,
			i === 0,
			view.choice?.title ?? '',
		));
	}
}

function render(view) {
	document.title = view.myTurn ? '▶ Your turn — Draft' : 'Draft — Setups';

	el.title.textContent = view.title;
	el.top.dataset.turn = view.turn ?? 'end';
	el.top.dataset.myTurn = String(view.myTurn);

	el.step.textContent = view.step
		? `Step ${view.step.number}/${view.step.total} · action ${view.progress.done + 1} of ${view.progress.total} · you are the ${view.me === 'host' ? 'Host' : 'Guest'}`
		: `${view.progress.done} of ${view.progress.total} actions`;

	renderLog(view);
	renderOptions(view);
}

const DRAFT_ENDED = 4000;

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 15_000;

let backoff = INITIAL_BACKOFF_MS;
let ended = false;

function connect() {
	const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
	const socket = new WebSocket(`${protocol}//${location.host}/api/draft/${draftId}/stream`);

	socket.addEventListener('open', () => { backoff = INITIAL_BACKOFF_MS; });

	socket.addEventListener('message', event => {
		const message = JSON.parse(event.data);

		if (message.type === 'end') {
			ended = true;
			return;
		}

		notify('');

		try {
			render(message.view);
		} catch (error) {
			console.error('Failed to render the view:', error);
			showBlocked('This page is on a different version than the server. Reload; if it persists, the bot needs a restart.');
		}
	});

	socket.addEventListener('close', async event => {
		if (ended || event.code === DRAFT_ENDED) return;

		const response = await fetch(`/api/draft/${draftId}`).catch(() => null);

		if (response && !response.ok) {
			const { error } = await response.json().catch(() => ({}));
			return showBlocked(error ?? 'Connection closed. Reload the page.');
		}

		notify('Reconnecting…', 'notice');
		setTimeout(connect, backoff);
		backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
	});
}

function showBlocked(reason) {
	el.title.textContent = 'I could not open this draft';
	el.step.textContent = reason;

	el.log.hidden = true;
	el.options.replaceChildren(
		element('p', 'end', 'Use /draft status on Discord to get your link again.'),
	);
}

connect();
