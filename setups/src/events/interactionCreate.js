const { Events, MessageFlags } = require('discord.js');

const draftInteractions = require('../discord/draftInteractions');

const NO_REPLY_POSSIBLE = new Set([10062, 40060]);

function report(context, error) {
	if (!NO_REPLY_POSSIBLE.has(error?.code)) {
		console.error(`${context}:`, error);
		return false;
	}

	console.warn(
		`${context}: interaction expired or already answered (${error.code}). `
		+ 'If this repeats, it is almost always more than one bot instance running.',
	);

	return true;
}

async function replyError(interaction, message) {
	const payload = { content: message, flags: MessageFlags.Ephemeral };

	if (interaction.replied || interaction.deferred) {
		await interaction.followUp(payload).catch(() => {});
	} else {
		await interaction.reply(payload).catch(() => {});
	}
}

module.exports = {
	name: Events.InteractionCreate,

	async execute(interaction) {
		if (interaction.isButton()) {
			if (!draftInteractions.isDraftComponent(interaction.customId)) return;

			try {
				await draftInteractions.handle(interaction);
			} catch (error) {
				const lost = report('Error in draft component', error);
				if (!lost) await replyError(interaction, 'Something went wrong handling that move.');
			}
			return;
		}

		if (!interaction.isChatInputCommand()) return;

		const command = interaction.client.commands.get(interaction.commandName);

		if (!command) {
			console.error(`Unknown command: ${interaction.commandName}`);
			return;
		}

		try {
			await command.execute(interaction);
		} catch (error) {
			const lost = report(`Error in /${interaction.commandName}`, error);
			if (!lost) await replyError(interaction, 'Something went wrong running that command.');
		}
	},
};
