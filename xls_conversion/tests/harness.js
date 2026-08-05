// Loads the real baptism-parser.js outside a browser and prints its rows as JSON.
//   node harness.js <transcription.md>
// Used by run_parser_test.py; also handy on its own for eyeballing a real run.
const path = require('path');
global.window = {};
require(path.join(__dirname, '..', 'baptism-parser.js'));
const fs = require('fs');
const text = fs.readFileSync(process.argv[2], 'utf8');
console.log(JSON.stringify(global.window.BaptismPsvParser.convertText(text), null, 1));
