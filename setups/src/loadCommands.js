const fs = require('node:fs');
const path = require('node:path');

const COMMANDS_DIR = path.join(__dirname, 'commands');

function loadCommands() {
	const commands = [];

	for (const file of fs.readdirSync(COMMANDS_DIR).filter(f => f.endsWith('.js'))) {
		const command = require(path.join(COMMANDS_DIR, file));

		if ('data' in command && 'execute' in command) {
			commands.push(command);
		} else {
			console.warn(`[WARN] src/commands/${file} does not export "data" and "execute".`);
		}
	}

	return commands;
}

module.exports = loadCommands;
