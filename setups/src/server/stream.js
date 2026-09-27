const { WebSocketServer } = require('ws');

const channels = new Map();

const CLOSE = { DRAFT_ENDED: 4000, UNAUTHORIZED: 4001 };

const HEARTBEAT_MS = 25_000;

let heartbeat = null;

function startHeartbeat() {
	if (heartbeat) return;

	heartbeat = setInterval(() => {
		for (const subs of channels.values()) {
			for (const sub of subs) {
				if (!sub.alive) {
					sub.ws.terminate();
					continue;
				}

				sub.alive = false;
				sub.ws.ping();
			}
		}
	}, HEARTBEAT_MS);

	heartbeat.unref?.();
}

function stopHeartbeatIfEmpty() {
	if (channels.size > 0 || !heartbeat) return;

	clearInterval(heartbeat);
	heartbeat = null;
}

const envelope = (type, data) => JSON.stringify({ type, ...data });

function subscribe(draftId, side, ws) {
	if (!channels.has(draftId)) channels.set(draftId, new Set());

	const sub = { ws, side, alive: true };
	channels.get(draftId).add(sub);
	startHeartbeat();

	ws.on?.('pong', () => { sub.alive = true; });

	const leave = () => {
		const subs = channels.get(draftId);
		if (!subs) return;

		subs.delete(sub);
		if (subs.size === 0) channels.delete(draftId);

		stopHeartbeatIfEmpty();
	};

	ws.on?.('close', leave);

	return leave;
}

function attach(server, onConnect, pathPattern = /^\/api\/draft\/[^/]+\/stream$/) {
	const wss = new WebSocketServer({ noServer: true });

	server.on('upgrade', (req, socket, head) => {
		if (!pathPattern.test(new URL(req.url, 'http://x').pathname)) return socket.destroy();

		const owner = onConnect(req);

		if (!owner) {
			socket.write('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');
			return socket.destroy();
		}

		wss.handleUpgrade(req, socket, head, ws => {
			subscribe(owner.draftId, owner.side, ws);
			ws.send(envelope('state', { view: owner.initial }));
		});
	});

	return wss;
}

function publish(draftId, buildView) {
	const subs = channels.get(draftId);
	if (!subs) return 0;

	const bySide = new Map();

	for (const { ws, side } of subs) {
		if (!bySide.has(side)) bySide.set(side, envelope('state', { view: buildView(side) }));

		try {
			ws.send(bySide.get(side));
		} catch {}
	}

	return subs.size;
}

function close(draftId) {
	const subs = channels.get(draftId);
	if (!subs) return;

	for (const { ws } of subs) {
		try {
			ws.send(envelope('end', {}));
			ws.close(CLOSE.DRAFT_ENDED, 'draft ended');
		} catch { /* already gone */ }
	}

	channels.delete(draftId);
	stopHeartbeatIfEmpty();
}


const total = () => [...channels.values()].reduce((sum, set) => sum + set.size, 0);

module.exports = { attach, subscribe, publish, close, total };
