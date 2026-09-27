const fs = require('node:fs');
const path = require('node:path');

const ASSETS_DIR = path.join(__dirname, '..', '..', 'assets');

const FOLDERS = {
	hull: 'hulls',
	turret: 'turrets',
	paint: 'paints',
};

const DISPLAY_OVERRIDES = {};

const titleize = id => id
	.split('-')
	.map(word => word.charAt(0).toUpperCase() + word.slice(1))
	.join(' ');

function loadCategory(kind) {
	const dir = path.join(ASSETS_DIR, FOLDERS[kind]);

	return fs.readdirSync(dir)
		.filter(file => file.toLowerCase().endsWith('.png'))
		.map(file => {
			const id = path.basename(file, path.extname(file));

			return {
				id,
				kind,
				name: DISPLAY_OVERRIDES[id] ?? titleize(id),
				file: path.join(dir, file),
				attachment: file,
			};
		})
		.sort((a, b) => a.name.localeCompare(b.name, 'en'));
}

const catalog = {
	hull: loadCategory('hull'),
	turret: loadCategory('turret'),
	paint: loadCategory('paint'),
};

const index = new Map(
	Object.values(catalog).flat().map(item => [`${item.kind}:${item.id}`, item]),
);

const getItem = (kind, id) => index.get(`${kind}:${id}`);

const list = kind => catalog[kind];

module.exports = {
	getItem,
	list,
	ASSETS_DIR,
	FOLDERS,
};
