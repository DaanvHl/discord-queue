require('dotenv').config();

const fs = require('node:fs');
const path = require('node:path');
const { Client, Collection, GatewayIntentBits } = require('discord.js');

const loadCommands = require('./src/loadCommands');
const lock = require('./src/lock');
const server = require('./src/server');
const flow = require('./src/flow');
const tunnel = require('./src/tunnel');

// Before anything else: make sure only one bot runs with this token. Two
// instances receive the same interaction and fight to answer it.
try {
	lock.protect();
} catch (error) {
	console.error(`\n${error.message}\n`);
	process.exit(1);
}

const client = new Client({ intents: [GatewayIntentBits.Guilds] });

client.commands = new Collection();
for (const command of loadCommands()) client.commands.set(command.data.name, command);

const eventsPath = path.join(__dirname, 'src', 'events');
for (const file of fs.readdirSync(eventsPath).filter(f => f.endsWith('.js'))) {
	const event = require(path.join(eventsPath, file));

	if (event.once) client.once(event.name, (...args) => event.execute(...args));
	else client.on(event.name, (...args) => event.execute(...args));
}

flow.useClient(client);

// Without this, every draft the players abandon stays in memory forever.
flow.scheduleSweep();

async function openToTheWorld() {
	if (process.env.BASE_URL) {
		console.log(`Fixed address: ${process.env.BASE_URL}`);
		return;
	}

	if (process.env.TUNNEL !== '1') {
		console.log('No tunnel: links only open on this machine. Set TUNNEL=1 in .env to expose it.');
		return;
	}

	tunnel.cleanupOnExit();

	const url = await tunnel.open({ port: server.port() });
	server.setBaseUrl(url);

	console.log(`Public address: ${url}`);
}

async function boot() {
	await server.start();

	// The tunnel is not required: if it fails the bot stays useful on this
	// machine, and the reason shows up instead of a silently broken link.
	await openToTheWorld().catch(error => {
		console.error(`\nCould not open the tunnel: ${error.message}`);
		console.error('Links will point at localhost.\n');
	});

	await client.login(process.env.DISCORD_TOKEN);
}

boot().catch(error => {
	console.error(`\nCould not start: ${error.message}\n`);
	process.exit(1);
});
