const { SlashCommandBuilder, MessageFlags } = require('discord.js');

const { createDraft, currentAction, sideOf } = require('../draft');
const sessions = require('../store/sessions');
const flow = require('../flow');
const server = require('../server');
const board = require('../discord/board');

const ephemeral = content => ({ content, flags: MessageFlags.Ephemeral });

async function start(interaction) {
	const opponent = interaction.options.getUser('opponent');

	if (opponent.bot) {
		return interaction.reply(ephemeral('You cannot draft against a bot.'));
	}

	if (opponent.id === interaction.user.id) {
		return interaction.reply(ephemeral('You need an opponent other than yourself.'));
	}

	const busy = sessions.busy(interaction.user.id, opponent.id);

	if (busy.length > 0) {
		const who = busy.includes(interaction.user.id) ? 'You are already' : `${opponent} is already`;
		return interaction.reply(ephemeral(`${who} in a draft. End it with \`/draft cancel\` before starting another.`));
	}

	const state = createDraft({
		id: sessions.newId(),
		hostId: interaction.user.id,
		guestId: opponent.id,
	});

	let session;

	try {
		session = sessions.create({
			channelId: interaction.channelId,
			state,
			names: {
				host: interaction.user.displayName ?? interaction.user.username,
				guest: opponent.displayName ?? opponent.username,
			},
		});
	} catch (error) {
		return interaction.reply(ephemeral(error.message));
	}

	await interaction.reply({
		...board.board(session),
		allowedMentions: { users: [state.guestId] },
	});

	const message = await interaction.fetchReply();
	sessions.update(state.id, { messageId: message.id });

	try {
		await interaction.followUp(ephemeral(
			`**Your draft** — you are the Host.\n${server.linkFor(session, 'host')}\n\n`
			+ `-# Once opened, the address shortens to ${server.draftUrl(session.id)}. `
			+ `${opponent} gets their link through the **Open my draft** button.`,
		));
	} catch (error) {
		console.error('Could not deliver the Host link:', error.message);
	}
}

const myDraft = interaction => sessions.ofPlayer(interaction.user.id);

async function status(interaction) {
	const session = myDraft(interaction);

	if (!session) return interaction.reply(ephemeral('You are not in any draft.'));

	const current = currentAction(session.state);
	const mySide = sideOf(session.state, interaction.user.id);

	const turn = current
		? `${current.side === 'host' ? 'Host' : 'Guest'}'s turn — step ${current.step.step}/26. You are the ${mySide === 'host' ? 'Host' : 'Guest'}.`
		: 'This draft has already ended.';

	const link = session.messageId
		? `\nhttps://discord.com/channels/${interaction.guildId}/${session.channelId}/${session.messageId}`
		: '';

	return interaction.reply(ephemeral(`${turn}${link}\n${server.linkFor(session, mySide)}`));
}

async function undo(interaction) {
	const session = myDraft(interaction);

	if (!session) return interaction.reply(ephemeral('You are not in any draft.'));

	await interaction.deferReply({ flags: MessageFlags.Ephemeral });

	const { error, undone } = await flow.undo(session);
	if (error) return interaction.editReply(error);

	return interaction.editReply(`Move undone (step ${undone.step}, ${undone.type}).`);
}

async function cancel(interaction) {
	const session = myDraft(interaction);

	if (!session) return interaction.reply(ephemeral('You are not in any draft.'));

	await interaction.deferReply({ flags: MessageFlags.Ephemeral });
	await flow.cancel(session);

	return interaction.editReply('Draft cancelled.');
}

module.exports = {
	data: new SlashCommandBuilder()
		.setName('draft')
		.setDescription('Setup draft in pick & ban format.')
		.addSubcommand(sub => sub
			.setName('start')
			.setDescription('Starts a draft against another player.')
			.addUserOption(opt => opt
				.setName('opponent')
				.setDescription('Who plays as Guest')
				.setRequired(true)))
		.addSubcommand(sub => sub
			.setName('status')
			.setDescription('Shows whose turn it is in your draft and returns your link.'))
		.addSubcommand(sub => sub
			.setName('undo')
			.setDescription('Undoes the last move of your draft.'))
		.addSubcommand(sub => sub
			.setName('cancel')
			.setDescription('Ends your draft.')),

	async execute(interaction) {
		const sub = interaction.options.getSubcommand();

		if (sub === 'start') return start(interaction);
		if (sub === 'status') return status(interaction);
		if (sub === 'undo') return undo(interaction);
		if (sub === 'cancel') return cancel(interaction);
	},
};
