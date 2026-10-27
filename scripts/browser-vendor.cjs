// Mechanical build of immutable npm assets; --check never writes files.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const pkg=require('../package.json');
const entries=[
 ['dompurify','dist/purify.min.js','purify.min.js','LICENSE'],
 ['marked','lib/marked.umd.js','marked.umd.js','LICENSE.md'],
];
for(const [name,source,target,license] of entries){
 const version=pkg.dependencies[name];
 assert.match(version,/^\d+\.\d+\.\d+$/);
 const root=path.join(__dirname,'..','node_modules',name);
 assert.equal(JSON.parse(fs.readFileSync(path.join(root,'package.json'))).version,version);
 const output=path.join(__dirname,'..','static','vendor',name+'-'+version);
 for(const [from,to] of [[source,target],[license,license]]){
  const content=fs.readFileSync(path.join(root,from)),dest=path.join(output,to);
  if(process.argv.includes('--check'))assert.deepEqual(fs.readFileSync(dest),content,'Vendor mismatch: '+dest);
  else {fs.mkdirSync(output,{recursive:true});fs.writeFileSync(dest,content);}
 }
}
console.log('Browser vendor assets match locked npm dependencies.');
