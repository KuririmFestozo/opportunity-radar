// Run the actual dashboard script with only the DOM surface it consumes.
// Select values deliberately follow browser semantics (unknown option => '').
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const elements = new Map();
function element(id, select = false) {
  return {
    id, options: [], listeners: {}, innerHTML: '', textContent: '', _value: '',
    get value() { return this._value; },
    set value(value) {
      value = String(value);
      this._value = select && !this.options.some(o => o.value === value) ? '' : value;
    },
    appendChild(option) { this.options.push(option); },
    addEventListener(event, listener) { this.listeners[event] = listener; },
  };
}
for (const match of input.html.matchAll(/\bid="([^"]+)"/g)) {
  elements.set(match[1], element(match[1]));
}
for (const match of input.html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>([\s\S]*?)<\/select>/g)) {
  const el = element(match[1], true);
  for (const option of match[2].matchAll(/<option\b[^>]*value="([^"]*)"([^>]*)>/g)) {
    el.options.push({value: option[1]});
    if (el.options.length === 1 || option[2].includes('selected')) el.value = option[1];
  }
  elements.set(match[1], el);
}
const context = vm.createContext({
  document: {
    getElementById: id => elements.get(id),
    createElement: () => element(''),
    querySelectorAll: () => [],
  },
});
const script = input.html.match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInContext(script.replace('__DASHBOARD_DATA__', () => JSON.stringify(input.data)), context);
const result = vm.runInContext(input.scenario, context);
process.stdout.write(JSON.stringify(result));
