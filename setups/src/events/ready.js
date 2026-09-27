const { Events } = require('discord.js');

module.exports = {
	name: Events.ClientReady,
	once: true,

	execute(client) {
		console.log(`Online as ${client.user.tag} (${client.commands.size} commands)`);
	},
};
