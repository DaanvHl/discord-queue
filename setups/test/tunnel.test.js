const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

const tunnel = require('../src/tunnel');
const server = require('../src/server');

test('recognises the URL in the middle of the cloudflared log', () => {
	const log = [
		'2026-07-25T21:55:23Z INF Requesting new quick Tunnel on trycloudflare.com...',
		'2026-07-25T21:55:29Z INF +------------------------------------------+',
		'2026-07-25T21:55:29Z INF |  Your quick Tunnel has been created!      |',
		'2026-07-25T21:55:29Z INF |  https://wells-worldwide-surfing-valid.trycloudflare.com  |',
		'2026-07-25T21:55:29Z INF +------------------------------------------+',
	].join('\n');

	assert.equal(
		log.match(tunnel.URL_PATTERN)[0],
		'https://wells-worldwide-surfing-valid.trycloudflare.com',
	);
});

test('does not confuse the line that only mentions the domain', () => {
	const early = '2026-07-25T21:55:23Z INF Requesting new quick Tunnel on trycloudflare.com...';

	assert.equal(early.match(tunnel.URL_PATTERN), null);
});

test('does not confuse the API endpoint with the match address', () => {
	const failure = '2026-07-26T02:31:02Z ERR Failed to request quick Tunnel '
		+ 'error="Post \\"https://api.trycloudflare.com/tunnel\\": context deadline exceeded"';

	assert.equal(failure.match(tunnel.URL_PATTERN), null);
});

test('does not take an address that has a path after the host', () => {
	const withPath = 'INF connecting to https://some-service.trycloudflare.com/v1/register';

	assert.equal(withPath.match(tunnel.URL_PATTERN), null);
});

test('each platform has its binary and its file name', () => {
	assert.equal(tunnel.BINARIES.win32.file, 'cloudflared.exe');
	assert.equal(tunnel.BINARIES.linux.file, 'cloudflared');

	assert.ok(!tunnel.BINARIES.linux.file.endsWith('.exe'));

	for (const { asset } of Object.values(tunnel.BINARIES)) {
		assert.match(asset, /^cloudflared-(windows|linux)-amd64(\.exe)?$/);
	}
});

test('the binary lives inside the project, not installed on the system', () => {
	assert.equal(path.basename(tunnel.DIR), 'tools');
	assert.ok(tunnel.DIR.includes('setups'));
});

test('the tunnel address outranks localhost', () => {
	const original = process.env.BASE_URL;
	delete process.env.BASE_URL;

	try {
		assert.match(server.baseUrl(), /^http:\/\/localhost:/);

		server.setBaseUrl('https://example.trycloudflare.com');
		assert.equal(server.baseUrl(), 'https://example.trycloudflare.com');

		const session = { id: 'abc123', tokens: { host: 'TH', guest: 'TG' } };
		assert.equal(server.linkFor(session, 'guest'), 'https://example.trycloudflare.com/d/abc123/TG');
		assert.equal(server.draftUrl('abc123'), 'https://example.trycloudflare.com/d/abc123/');
	} finally {
		server.setBaseUrl(null);
		if (original) process.env.BASE_URL = original;
	}
});

test('a trailing slash does not become a double slash in the link', () => {
	try {
		server.setBaseUrl('https://example.trycloudflare.com/');

		assert.equal(server.draftUrl('abc123'), 'https://example.trycloudflare.com/d/abc123/');
	} finally {
		server.setBaseUrl(null);
	}
});
