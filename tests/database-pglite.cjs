// 별도 임시 폴더에 설치한 PGlite만 사용. .env/운영 연결/실제 데이터 사용 없음.
// node tests/database-pglite.cjs <temporary-npm-prefix>
const fs = require('node:fs');
const path = require('node:path');
const prefix = process.argv[2];
if (!prefix) throw new Error('임시 PGlite 설치 폴더를 지정하세요.');
const { PGlite } = require(path.resolve(prefix, 'node_modules/@electric-sql/pglite'));
const root = path.resolve(__dirname, '..');
const allowed = new Set([
  'supabase/20260730_response_cache.sql',
  'supabase/20260730_response_cache_scopes.sql',
  'supabase/20260919_runtime_safety.sql',
]);
function expand(file) {
  return fs.readFileSync(path.join(root,file),'utf8').split(/\r?\n/).map(line=>{
    if (line.startsWith('\\set ')) return '';
    if (line.startsWith('\\i ')) {
      const target=line.slice(3).trim();
      if (!allowed.has(target)) throw new Error('Unexpected SQL include');
      return expand(target);
    }
    return line;
  }).join('\n');
}
(async()=>{
  const db=new PGlite(); // 항상 메모리 DB. 원격 연결 매개변수 없음.
  try {
    console.log((await db.query('select version()')).rows[0].version);
    const result=await db.exec(expand('tests/database_regression.sql'));
    console.log(result[result.length-1].rows[0].result);
    console.log('주의: 단일 연결 검증입니다. 다중 세션 경합은 native PostgreSQL CI에서 확인합니다.');
  } catch(error) {
    console.error({message:error.message, code:error.code, where:error.where});
    process.exitCode=1;
  } finally {
    await db.close();
  }
})();
