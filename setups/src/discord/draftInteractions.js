const { MessageFlags } = require('discord.js');

const { sideOf } = require('../draft');
const sessions = require('../store/sessions');
const flow = require('../flow');
const server = require('../server');
const customId = require('./customId');

const ephemeral = content => ({ content, flags: MessageFlags.Ephemeral });

async function sendLink(interaction, session, side) {
	const link = server.linkFor(session, side);

	return interaction.reply(ephemeral(
		`**Your draft** — you are the ${side === 'host' ? 'Host' : 'Guest'}.\n${link}\n\n`
		+ '-# This link is yours: whoever opens it plays as you. Once opened, the address shortens '
		+ `to ${server.draftUrl(session.id)} — your identity is kept in the browser.`,
	));
}

async function cancelFromButton(interaction, session) {
	await interaction.deferReply({ flags: MessageFlags.Ephemeral });
	await flow.cancel(session);

	return interaction.editReply('Draft cancelled.');
}

async function handle(interaction) {
	const data = customId.decode(interaction.customId);
	if (!data) return;

	const session = sessions.get(data.draftId);

	if (!session) {
		return interaction.reply(ephemeral('This draft no longer exists — the bot has probably restarted. Start another one with `/draft start`.'));
	}

	const side = sideOf(session.state, interaction.user.id);
	if (!side) return interaction.reply(ephemeral('You are not part of this draft.'));

	if (data.action === 'link') return sendLink(interaction, session, side);
	if (data.action === 'cancel') return cancelFromButton(interaction, session);

	return interaction.reply(ephemeral(`Unknown action: ${data.action}`));
}

module.exports = { handle, isDraftComponent: customId.isDraft };
