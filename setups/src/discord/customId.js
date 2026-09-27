const PREFIX = 'd';
const LIMIT = 100;

function encode(draftId, seq, action) {
	const id = [PREFIX, draftId, seq, action].join(':');

	if (id.length > LIMIT) {
		throw new Error(`customId exceeded ${LIMIT} characters: ${id}`);
	}

	return id;
}

function decode(customId) {
	const [prefix, draftId, seq, action] = customId.split(':');
	if (prefix !== PREFIX) return null;

	return { draftId, seq: Number(seq), action };
}

const isDraft = customId => customId.startsWith(`${PREFIX}:`);

module.exports = { encode, decode, isDraft };
