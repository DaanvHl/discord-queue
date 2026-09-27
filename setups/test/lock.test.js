const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const lock = require('../src/lock');

const tempFile = () => path.join(
	fs.mkdtempSync(path.join(os.tmpdir(), 'setups-lock-')),
	'bot.lock',
);

test('the first instance takes the lock', () => {
	const file = tempFile();
	const drop = lock.acquire({ file, pid: 111 });

	assert.equal(typeof drop, 'function');
	assert.deepEqual(JSON.parse(fs.readFileSync(file, 'utf8')).pid, 111);
});

test('the second instance is refused while the first is alive', () => {
	const file = tempFile();
	lock.acquire({ file, pid: 111, alive: () => true });

	assert.throws(
		() => lock.acquire({ file, pid: 222, alive: () => true }),
		error => error.code === 'BOT_ALREADY_RUNNING' && error.pid === 111,
	);
});

test('a lock left by a dead process counts as stale', () => {
	const file = tempFile();
	lock.acquire({ file, pid: 111, alive: () => true });

	lock.acquire({ file, pid: 222, alive: () => false });

	assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).pid, 222);
});

test('re-entering with the same pid is not a conflict', () => {
	const file = tempFile();
	lock.acquire({ file, pid: 111, alive: () => true });

	assert.doesNotThrow(() => lock.acquire({ file, pid: 111, alive: () => true }));
});

test('releasing the lock frees it for the next one', () => {
	const file = tempFile();
	const drop = lock.acquire({ file, pid: 111, alive: () => true });

	assert.equal(drop(), true);
	assert.equal(fs.existsSync(file), false);
	assert.doesNotThrow(() => lock.acquire({ file, pid: 222, alive: () => true }));
});

test('nobody releases another process lock', () => {
	const file = tempFile();
	lock.acquire({ file, pid: 111, alive: () => true });

	assert.equal(lock.release({ file, pid: 222 }), false);
	assert.equal(fs.existsSync(file), true);
});

test('a corrupted file does not block startup', () => {
	const file = tempFile();
	fs.writeFileSync(file, 'this is not json', 'utf8');

	assert.doesNotThrow(() => lock.acquire({ file, pid: 111 }));
});

test('processAlive recognises this process and refuses a nonexistent pid', () => {
	assert.equal(lock.processAlive(process.pid), true);

	assert.equal(lock.processAlive(0x7fffffff), false);
});
