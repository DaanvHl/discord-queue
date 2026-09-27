const catalog = require('./catalog');
const rules = require('./rules');
const state = require('./state');
const { ORDER, TOTAL_ACTIONS, SETUPS_PER_SIDE } = require('./order');

module.exports = {
	ORDER,
	TOTAL_ACTIONS,
	SETUPS_PER_SIDE,

	getItem: catalog.getItem,
	list: catalog.list,
	ASSETS_DIR: catalog.ASSETS_DIR,
	FOLDERS: catalog.FOLDERS,

	RULES: rules.RULES,
	optionsFor: rules.optionsFor,

	STATUS: state.STATUS,
	createDraft: state.createDraft,
	currentAction: state.currentAction,
	sideOf: state.sideOf,
	progress: state.progress,
	applyAction: state.applyAction,
	cancel: state.cancel,
	undo: state.undo,
};
