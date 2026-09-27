const path = require('node:path');
const http = require('node:http');
const express = require('express');

const { ASSETS_DIR, createDraft } = require('../draft');
const sessions = require('../store/sessions');
const flow = require('../flow');
const stream = require('./stream');
const { view } = require('./view');

const WEB = path.join(__dirname, '..', '..', 'web');

const DEFAULT_PORT = 3000;

let currentPort = Number(process.env.PORT) || DEFAULT_PORT;

let externalBase = null;

const baseUrl = () => (externalBase || process.env.BASE_URL || `http://localhost:${currentPort}`).replace(/\/$/, '');

const setBaseUrl = url => { externalBase = url; };

const linkFor = (session, side) => `${baseUrl()}/d/${session.id}/${session.tokens[side]}`;

const draftUrl = draftId => `${baseUrl()}/d/${draftId}/`;

const cookieName = draftId => `draft_${draftId}`;

const COOKIE_MAX_AGE_S = 4 * 60 * 60;

function cookies(req) {
	const raw = req.headers.cookie;
	if (!raw) return {};

	return Object.fromEntries(
		raw.split(';').map(part => {
			const equals = part.indexOf('=');
			if (equals < 0) return [part.trim(), ''];

			return [part.slice(0, equals).trim(), decodeURIComponent(part.slice(equals + 1).trim())];
		}),
	);
}

function storeToken(res, draftId, token) {
	const secure = baseUrl().startsWith('https://');

	res.append('Set-Cookie', [
		`${cookieName(draftId)}=${encodeURIComponent(token)}`,
		'Path=/',
		`Max-Age=${COOKIE_MAX_AGE_S}`,
		'HttpOnly',
		'SameSite=Lax',
		...(secure ? ['Secure'] : []),
	].join('; '));
}

function resolveOwner({ draftId, fromCookie, token }) {
	const owner = sessions.byToken(fromCookie || token);

	if (!owner) {
		return { status: 401, error: 'Invalid link or the draft has ended. Get a new link with `/draft status` on Discord.' };
	}

	if (owner.session.id !== draftId) {
		return { status: 403, error: 'This link belongs to another draft.' };
	}

	return { owner };
}

function authenticate(req, res) {
	const { owner, status, error } = resolveOwner({
		draftId: req.params.id,
		fromCookie: cookies(req)[cookieName(req.params.id)],
		token: req.query.t || req.body?.t,
	});

	if (!owner) {
		res.status(status).json({ error });
		return null;
	}

	return owner;
}

function authenticateUpgrade(req) {
	const url = new URL(req.url, 'http://x');

	const draftId = url.pathname.split('/')[3];

	const { owner } = resolveOwner({
		draftId,
		fromCookie: cookies(req)[cookieName(draftId)],
		token: url.searchParams.get('t'),
	});

	if (!owner) return null;

	return { draftId: owner.session.id, side: owner.side, initial: view(owner.session, owner.side) };
}

function createApp() {
	const app = express();

	app.use(express.json());

	app.use('/assets', express.static(ASSETS_DIR, {
		maxAge: '1h',
		fallthrough: false,
	}));

	app.use(express.static(WEB));

	app.get('/d/:id/:token', (req, res, next) => {
		const owner = sessions.byToken(req.params.token);

		if (!owner) return next();

		if (owner.session.id !== req.params.id) {
			return res.status(403).send('This link belongs to another draft.');
		}

		storeToken(res, owner.session.id, req.params.token);
		return res.redirect(303, `/d/${owner.session.id}/`);
	});

	app.get('/d/:id', (req, res) => {
		res.sendFile(path.join(WEB, 'index.html'));
	});

	app.get('/api/draft/:id', (req, res) => {
		const owner = authenticate(req, res);
		if (!owner) return;

		res.json(view(owner.session, owner.side));
	});

	app.post('/api/draft/:id/move', async (req, res) => {
		const owner = authenticate(req, res);
		if (!owner) return;

		const { item } = req.body ?? {};
		if (typeof item !== 'string') return res.status(400).json({ error: 'Move without an item.' });

		const { error } = await flow.choose(owner.session, owner.side, item);
		if (error) return res.status(409).json({ error });

		res.json({ ok: true });
	});

	// Machine-to-machine: another bot creates a draft for two players and gets back
	// their private links. Only enabled when a shared secret is configured.
	const API_SECRET = process.env.SETUPS_SECRET || process.env.SECRET || '';

	if (API_SECRET) {
		app.post('/api/drafts', (req, res) => {
			if (req.get('x-setups-secret') !== API_SECRET) {
				return res.status(401).json({ error: 'Unauthorized.' });
			}

			const { hostId, guestId, hostName, guestName, channelId, meta } = req.body ?? {};

			if (!hostId || !guestId || hostId === guestId) {
				return res.status(400).json({ error: 'Distinct hostId and guestId are required.' });
			}

			if (sessions.busy(hostId, guestId).length > 0) {
				return res.status(409).json({ error: 'One of these players is already in a draft.' });
			}

			const state = createDraft({ id: sessions.newId(), hostId, guestId });

			let session;
			try {
				session = sessions.create({
					channelId: channelId ?? null,
					state,
					names: { host: hostName ?? 'Host', guest: guestName ?? 'Guest' },
				});
			} catch (error) {
				return res.status(409).json({ error: error.message });
			}

			sessions.update(session.id, { meta: meta ?? null });

			return res.json({
				id: session.id,
				hostUrl: linkFor(session, 'host'),
				guestUrl: linkFor(session, 'guest'),
			});
		});
	}

	app.get('/api/health', (req, res) => res.json({
		ok: true,
		drafts: sessions.size(),
		limit: sessions.LIMIT,
		openPages: stream.total(),
		memoryMb: Math.round(process.memoryUsage().heapUsed / 1024 / 1024),
	}));

	return app;
}

function createServer() {
	const server = http.createServer(createApp());
	stream.attach(server, authenticateUpgrade);

	return server;
}

function start({ port = Number(process.env.PORT) || DEFAULT_PORT } = {}) {
	return new Promise((resolve, reject) => {
		const server = createServer().listen(port);

		server.once('listening', () => {
			currentPort = server.address().port;
			console.log(`Draft at ${baseUrl()}`);
			resolve(server);
		});

		server.once('error', reject);
	});
}

module.exports = { createServer, start, linkFor, draftUrl, baseUrl, setBaseUrl, port: () => currentPort };
