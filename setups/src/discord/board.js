const { ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder } = require('discord.js');

const { ORDER, currentAction, getItem, progress, STATUS } = require('../draft');
const customId = require('./customId');

const COLOR = {
	host: 0x3b82f6,
	guest: 0xef4444,
	completed: 0x22c55e,
	cancelled: 0x6b7280,
};

const SIDE_LABEL = { host: 'Host', guest: 'Guest' };
const KIND_LABEL = { hull: 'hull', turret: 'turret', paint: 'paint' };

function formatBans(state, side) {
	const bans = state.bans[side];
	if (bans.length === 0) return '_no bans_';

	const byKind = { hull: [], turret: [], paint: [] };
	for (const ban of bans) byKind[ban.kind].push(getItem(ban.kind, ban.id)?.name ?? ban.id);

	return Object.entries(byKind)
		.filter(([, names]) => names.length > 0)
		.map(([kind, names]) => `**${KIND_LABEL[kind]}:** ${names.map(n => `~~${n}~~`).join(', ')}`)
		.join('\n');
}

function formatSetups(state, side) {
	const setups = state.picks[side];
	if (setups.length === 0) return '_no setups_';

	return setups
		.map(setup => {
			const turret = getItem('turret', setup.turret)?.name ?? setup.turret;
			const hull = getItem('hull', setup.hull)?.name ?? setup.hull;
			const paint = setup.paint
				? getItem('paint', setup.paint)?.name ?? setup.paint
				: '_paint pending_';

			return `\`${setup.n}.\` ${turret} · ${hull} · ${paint}`;
		})
		.join('\n');
}

function finalRecord(state) {
	const embed = new EmbedBuilder()
		.setTitle('Draft — Tanki')
		.addFields(
			{ name: '🔵 Host', value: `<@${state.hostId}>\n${formatBans(state, 'host')}`, inline: true },
			{ name: '🔴 Guest', value: `<@${state.guestId}>\n${formatBans(state, 'guest')}`, inline: true },
			{ name: '​', value: '​' },
			{ name: 'Host setups', value: formatSetups(state, 'host'), inline: true },
			{ name: 'Guest setups', value: formatSetups(state, 'guest'), inline: true },
		);

	if (state.status === STATUS.COMPLETED) {
		embed.setColor(COLOR.completed).setDescription('✅ **Draft completed.** All 14 setups are locked in.');
	} else {
		embed.setColor(COLOR.cancelled).setDescription('❌ **Draft cancelled.**');
	}

	return embed;
}

const scoreline = state => `🔵 <@${state.hostId}> (Host) vs 🔴 <@${state.guestId}> (Guest)`;

function board(session) {
	const { state } = session;
	const current = currentAction(state);
	const { done, total } = progress(state);

	const base = { attachments: [], files: [], allowedMentions: { parse: [] } };

	if (!current) {
		return { ...base, content: `**Draft** · ${scoreline(state)}`, embeds: [finalRecord(state)], components: [] };
	}

	const seq = state.history.length;

	return {
		...base,
		content: `**Draft** · ${scoreline(state)}\n`
			+ `Step ${ORDER[state.stepIndex].step}/${ORDER.length} · action ${done + 1} of ${total} — `
			+ `**${SIDE_LABEL[current.side]}**'s turn.\n`
			+ 'Use **Open my draft** to get your link.',
		embeds: [],
		components: [new ActionRowBuilder().addComponents(
			new ButtonBuilder()
				.setCustomId(customId.encode(state.id, seq, 'link'))
				.setLabel('Open my draft')
				.setStyle(ButtonStyle.Primary),
			new ButtonBuilder()
				.setCustomId(customId.encode(state.id, seq, 'cancel'))
				.setLabel('Cancel draft')
				.setStyle(ButtonStyle.Danger),
		)],
	};
}

module.exports = { board };
