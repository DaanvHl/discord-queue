const test = require('node:test');
const assert = require('node:assert');

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'setups-server-'));
process.env.DATA_DIR = DIR;

const { createDraft, currentAction, optionsFor } = require('../src/draft');
const sessions = require('../src/store/sessions');
const server = require('../src/server');

let base;
let http;

test.before(async () => {
	http = server.createServer().listen(0);
	await new Promise(resolve => http.once('listening', resolve));
	base = `http://localhost:${http.address().port}`;
});

test.after(() => {
	http?.close();

	sessions.all().forEach(s => sessions.remove(s.id));

	fs.rmSync(DIR, { recursive: true, force: true });
});

let counter = 0;

function newSession() {
	counter += 1;
	const id = `t${String(counter).padStart(7, '0')}`;

	const state = createDraft({ id, hostId: `h${counter}`, guestId: `g${counter}` });
	return sessions.create({
		channelId: `channel-${id}`,
		state,
		names: { host: 'Desert', guest: 'Lever' },
	});
}

const fetchPath = (route, token) => fetch(`${base}${route}${route.includes('?') ? '&' : '?'}t=${token ?? ''}`);

const play = (session, token, item) => fetch(`${base}/api/draft/${session.id}/move?t=${token}`, {
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify({ item }),
});

const clickable = v => Object.values(v.grid).flat().filter(item => item.playable);

const firstItem = session => {
	const { action } = currentAction(session.state);
	const opts = optionsFor(session.state, action);

	return (action.type === 'ban' ? opts.items : action.type === 'paint' ? opts.paints : opts.turrets)[0].id;
};

test('the redemption link becomes a cookie and shortens the URL', async () => {
	const session = newSession();

	const response = await fetch(`${base}/d/${session.id}/${session.tokens.host}`, { redirect: 'manual' });

	assert.equal(response.status, 303, 'expected a redirect swapping the URL for one without a token');
	assert.equal(response.headers.get('location'), `/d/${session.id}/`);

	const cookie = response.headers.get('set-cookie');
	assert.match(cookie, new RegExp(`^draft_${session.id}=`), `unexpected cookie: ${cookie}`);
	assert.match(cookie, /HttpOnly/i, 'without HttpOnly the page JavaScript would read the token');
	assert.match(cookie, /SameSite=Lax/i);
	assert.ok(cookie.includes(session.tokens.host), 'the cookie does not carry the token');
});

test('a wrong token on redemption does not become a cookie', async () => {
	const session = newSession();

	const madeUp = await fetch(`${base}/d/${session.id}/made-up-token`, { redirect: 'manual' });
	assert.equal(madeUp.status, 404);
	assert.equal(madeUp.headers.get('set-cookie'), null);

	const other = newSession();
	const swapped = await fetch(`${base}/d/${session.id}/${other.tokens.host}`, { redirect: 'manual' });

	assert.equal(swapped.status, 403);
	assert.equal(swapped.headers.get('set-cookie'), null);
});

test('after redemption, the clean URL already identifies the player', async () => {
	const session = newSession();

	const redeem = await fetch(`${base}/d/${session.id}/${session.tokens.guest}`, { redirect: 'manual' });
	const cookie = redeem.headers.get('set-cookie').split(';')[0];

	const view = await (await fetch(`${base}/api/draft/${session.id}`, { headers: { cookie } })).json();

	assert.equal(view.me, 'guest');
	assert.equal(view.myTurn, false, 'step 1 belongs to the Host');
});

test('a cookie from one draft does not open another', async () => {
	const a = newSession();
	const b = newSession();

	const redeem = await fetch(`${base}/d/${a.id}/${a.tokens.host}`, { redirect: 'manual' });
	const cookie = redeem.headers.get('set-cookie').split(';')[0];

	const response = await fetch(`${base}/api/draft/${b.id}`, { headers: { cookie } });
	assert.equal(response.status, 401);
});

test('the match URL carries no secret', async () => {
	const session = newSession();

	const url = server.draftUrl(session.id);

	assert.match(url, /\/d\/[a-z0-9-]+\/$/i);
	assert.ok(!url.includes(session.tokens.host));
	assert.ok(!url.includes(session.tokens.guest));
	assert.ok(!url.includes('#') && !url.includes('?'), `a parameter leaked into the URL: ${url}`);
});

test('without a token nothing can be read', async () => {
	const session = newSession();

	assert.equal((await fetchPath(`/api/draft/${session.id}`)).status, 401);
	assert.equal((await fetchPath(`/api/draft/${session.id}`, 'made-up')).status, 401);
});

test('a token from one draft does not open another', async () => {
	const a = newSession();
	const b = newSession();

	const response = await fetchPath(`/api/draft/${b.id}`, a.tokens.host);
	assert.equal(response.status, 403);
});

test('a token is revoked along with the draft', async () => {
	const session = newSession();
	const token = session.tokens.host;

	assert.equal((await fetchPath(`/api/draft/${session.id}`, token)).status, 200);

	sessions.remove(session.id);
	assert.equal((await fetchPath(`/api/draft/${session.id}`, token)).status, 401);
});

test('each side receives its own view', async () => {
	const session = newSession();

	const host = await (await fetchPath(`/api/draft/${session.id}`, session.tokens.host)).json();
	const guest = await (await fetchPath(`/api/draft/${session.id}`, session.tokens.guest)).json();

	assert.equal(host.me, 'host');
	assert.equal(guest.me, 'guest');

	assert.equal(host.myTurn, true);
	assert.ok(clickable(host).length > 0);

	assert.equal(guest.myTurn, false);
	assert.equal(guest.choice, null, 'the Guest received options off turn');
});

test('the wrong side does not play', async () => {
	const session = newSession();

	const response = await play(session, session.tokens.guest, firstItem(session));

	assert.equal(response.status, 409);
	assert.match((await response.json()).error, /not your turn/i);
	assert.equal(session.state.history.length, 0, 'the improper move went through');
});

test('an item outside the list is refused before reaching the engine', async () => {
	const session = newSession();

	const response = await play(session, session.tokens.host, 'item-that-does-not-exist');

	assert.equal(response.status, 409);
	assert.match((await response.json()).error, /not available/i);
});

test('a move without an item is a malformed request, not a rule error', async () => {
	const session = newSession();

	const response = await fetch(`${base}/api/draft/${session.id}/move?t=${session.tokens.host}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({}),
	});

	assert.equal(response.status, 400);
});

test('a valid move advances the draft', async () => {
	const session = newSession();
	const item = firstItem(session);

	const response = await play(session, session.tokens.host, item);

	assert.equal(response.status, 200);
	assert.equal(session.state.history.length, 1);
	assert.equal(session.state.bans.host[0].id, item);

	const guest = await (await fetchPath(`/api/draft/${session.id}`, session.tokens.guest)).json();
	assert.equal(guest.myTurn, true);
});

test('picking the turret is not a move, it only swaps the list', async () => {
	const session = newSession();

	while (currentAction(session.state).action.type !== 'pick') {
		const side = currentAction(session.state).side;
		await play(session, session.tokens[side], firstItem(session));
	}

	const before = session.state.history.length;
	const side = currentAction(session.state).side;
	const turret = firstItem(session);

	assert.equal((await play(session, session.tokens[side], turret)).status, 200);
	assert.equal(session.state.history.length, before, 'the turret became a move on its own');
	assert.equal(session.pendingTurret, turret);

	const view = await (await fetchPath(`/api/draft/${session.id}`, session.tokens[side])).json();
	assert.equal(view.choice.type, 'hull');
	assert.equal(view.choice.pendingTurret.id, turret);

	assert.equal((await play(session, session.tokens[side], clickable(view)[0].id)).status, 200);
	assert.equal(session.state.history.length, before + 1);
	assert.equal(session.pendingTurret, null);
});

test('the whole draft can be completed through the page', async () => {
	const session = newSession();
	const draftId = session.id;
	let clicks = 0;

	while (currentAction(session.state)) {
		const side = currentAction(session.state).side;
		const view = await (await fetchPath(`/api/draft/${draftId}`, session.tokens[side])).json();

		const response = await play(session, session.tokens[side], clickable(view)[0].id);
		assert.equal(response.status, 200, `click ${clicks}: ${JSON.stringify(await response.json())}`);

		clicks += 1;
		assert.ok(clicks < 100, 'the draft never ended — stuck loop');
	}

	assert.equal(session.state.status, 'completed');
	assert.equal(session.state.picks.host.length, 7);
	assert.equal(session.state.picks.guest.length, 7);

	assert.equal(sessions.get(draftId), undefined);
	assert.equal((await fetchPath(`/api/draft/${draftId}`, session.tokens.host)).status, 401);
});

function openStream(session, token) {
	const ws = new WebSocket(`${base.replace('http', 'ws')}/api/draft/${session.id}/stream?t=${token}`);

	const queue = [];
	let deliver = null;

	ws.addEventListener('message', event => {
		const message = JSON.parse(event.data);

		if (deliver) {
			deliver(message);
			deliver = null;
		} else {
			queue.push(message);
		}
	});

	const next = () => (queue.length > 0
		? Promise.resolve(queue.shift())
		: new Promise((ok, fail) => {
			deliver = ok;
			ws.addEventListener('close', () => fail(new Error('the stream closed before the message')), { once: true });
		}));

	const opened = new Promise((ok, fail) => {
		ws.addEventListener('open', ok, { once: true });
		ws.addEventListener('error', () => fail(new Error('the handshake was refused')), { once: true });
	});

	return { ws, next, opened, closed: () => new Promise(ok => ws.addEventListener('close', ok, { once: true })) };
}

test('the stream sends the initial state and then every change', async () => {
	const session = newSession();
	const stream = openStream(session, session.tokens.guest);

	await stream.opened;

	const initial = await stream.next();
	assert.equal(initial.type, 'state');
	assert.equal(initial.view.me, 'guest');
	assert.equal(initial.view.myTurn, false, 'step 1 belongs to the Host');

	await play(session, session.tokens.host, firstItem(session));

	const after = await stream.next();
	assert.equal(after.view.myTurn, true, 'the Guest was not told the turn had flipped');
	assert.equal(after.view.history.length, 1);

	stream.ws.close();
});

test('without a token the stream does not even open', async () => {
	const session = newSession();
	const stream = openStream(session, 'made-up');

	await assert.rejects(stream.opened, /refused/, 'the handshake passed without a valid token');
});

test('the stream warns and closes when the draft ends', async () => {
	const session = newSession();
	const stream = openStream(session, session.tokens.host);

	await stream.opened;
	await stream.next();

	while (currentAction(session.state)) {
		const side = currentAction(session.state).side;
		const view = await (await fetchPath(`/api/draft/${session.id}`, session.tokens[side])).json();
		await play(session, session.tokens[side], clickable(view)[0].id);
	}

	await stream.closed();
	assert.equal(stream.ws.readyState, WebSocket.CLOSED);
});
