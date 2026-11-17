#!/usr/bin/env node
// Roda uma coleção Postman v2.1 sem o Postman nem o newman: o bin/e2e_postman.py a usa contra o
// gateway local. Cobre o que as coleções do projeto usam: variáveis de coleção e de ambiente
// ({{x}}), scripts de prerequest e de test (pm.test, pm.expect, pm.response,
// pm.collectionVariables), corpo raw e query string.
//
// As mensagens entre os serviços são assíncronas: uma requisição GET com teste falhando é
// repetida (até --retries vezes, com --delay ms entre elas), como a descrição da coleção pede.
// `--pay-after "<trecho do nome>"` chama POST {baseUrl}/__e2e/pay/{{serviceOrderId}} depois da
// requisição cujo nome contém o trecho: o pagamento que, em hml, o cliente faz no sandbox.
//
// Uso: node postman-runner.js <coleção.json> <ambiente.json> [--set chave=valor]... [--retries N]
//        [--delay ms] [--pay-after trecho] [--json saida.json]
'use strict';

const fs = require('fs');
const vm = require('vm');

function parseArgs(argv) {
  const opts = { set: {}, retries: 15, delay: 1500, payAfter: null, json: null, files: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--set') { const [k, ...v] = argv[++i].split('='); opts.set[k] = v.join('='); }
    else if (a === '--retries') opts.retries = Number(argv[++i]);
    else if (a === '--delay') opts.delay = Number(argv[++i]);
    else if (a === '--pay-after') opts.payAfter = argv[++i];
    else if (a === '--json') opts.json = argv[++i];
    else opts.files.push(a);
  }
  return opts;
}

class AssertionFailed extends Error {}

// O pedaço do chai (BDD) que os scripts usam: to/be/have/at encadeiam; eql, above, least,
// a, include, exist, false, status terminam.
function expect(actual) {
  let negate = false;
  const check = (ok, msg) => {
    if (negate ? ok : !ok) throw new AssertionFailed((negate ? 'não esperado: ' : '') + msg);
  };
  const chain = {
    eql: (v) => check(JSON.stringify(actual) === JSON.stringify(v), `${JSON.stringify(actual)} deveria ser ${JSON.stringify(v)}`),
    equal: (v) => check(actual === v, `${JSON.stringify(actual)} deveria ser ${JSON.stringify(v)}`),
    above: (v) => check(actual > v, `${actual} deveria ser maior que ${v}`),
    least: (v) => check(actual >= v, `${actual} deveria ser pelo menos ${v}`),
    a: (t) => check(typeof actual === t || (t === 'array' && Array.isArray(actual)), `${JSON.stringify(actual)} deveria ser ${t}`),
    an: (t) => chain.a(t),
    include: (v) => check(actual != null && actual.includes(v), `${JSON.stringify(actual)} deveria conter ${JSON.stringify(v)}`),
    get exist() { check(actual !== undefined && actual !== null, 'deveria existir'); return chain; },
    get true() { check(actual === true, `${actual} deveria ser true`); return chain; },
    get false() { check(actual === false, `${actual} deveria ser false`); return chain; },
    get not() { negate = !negate; return chain; },
  };
  for (const word of ['to', 'be', 'have', 'at', 'been', 'is', 'that', 'and']) {
    Object.defineProperty(chain, word, { get: () => chain });
  }
  return chain;
}

function resolve(text, vars) {
  return typeof text === 'string' ? text.replace(/\{\{([\w.-]+)\}\}/g, (m, k) => (k in vars() ? String(vars()[k]) : m)) : text;
}

function* requests(items, folder = '') {
  for (const item of items) {
    if (item.item) yield* requests(item.item, item.name);
    else yield { folder, item };
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const [collectionFile, environmentFile] = opts.files;
  const collection = JSON.parse(fs.readFileSync(collectionFile, 'utf8'));
  const environment = {};
  for (const v of JSON.parse(fs.readFileSync(environmentFile, 'utf8')).values || []) {
    if (v.enabled !== false) environment[v.key] = v.value;
  }
  Object.assign(environment, opts.set);
  const collectionVars = {};
  for (const v of collection.variable || []) collectionVars[v.key] = v.value;
  const vars = () => ({ ...environment, ...collectionVars });

  const run = (exec, context) => {
    if (!exec) return [];
    const results = [];
    const pm = {
      ...context,
      collectionVariables: { get: (k) => collectionVars[k], set: (k, v) => { collectionVars[k] = v; } },
      environment: { get: (k) => environment[k], set: (k, v) => { environment[k] = v; } },
      variables: { get: (k) => vars()[k] },
      expect,
      test: (name, fn) => {
        try { fn(); results.push({ name, ok: true }); }
        catch (e) { results.push({ name, ok: false, error: e.message }); }
      },
    };
    vm.runInNewContext(Array.isArray(exec) ? exec.join('\n') : exec, { pm, console, JSON, Math, String, Array, Number });
    return results;
  };
  const scripts = (owner, listen) => (owner.event || []).filter((e) => e.listen === listen).map((e) => e.script.exec);

  const report = [];
  let failed = 0;
  for (const { folder, item } of requests(collection.item)) {
    const req = item.request;
    let outcome;
    for (let attempt = 1; ; attempt++) {
      for (const exec of [...scripts(collection, 'prerequest'), ...scripts(item, 'prerequest')]) run(exec, {});
      const url = resolve(typeof req.url === 'string' ? req.url : req.url.raw, vars);
      const headers = {};
      for (const h of req.header || []) if (!h.disabled) headers[h.key] = resolve(h.value, vars);
      const body = req.body && req.body.mode === 'raw' ? resolve(req.body.raw, vars) : undefined;
      let status = 0; let text = '';
      try {
        const res = await fetch(url, { method: req.method, headers, body });
        status = res.status; text = await res.text();
      } catch (e) { text = String(e); }
      const response = {
        code: status,
        text: () => text,
        json: () => JSON.parse(text),
        to: { have: { status: (code) => { if (status !== code) throw new AssertionFailed(`status ${status}, esperado ${code}: ${text.slice(0, 200)}`); } } },
      };
      const tests = scripts(item, 'test').flatMap((exec) => run(exec, { response, request: { headers: { has: (k) => k in headers } } }));
      outcome = { folder, name: item.name, method: req.method, url, status, attempt, tests };
      const ok = tests.every((t) => t.ok);
      if (ok || req.method !== 'GET' || attempt > opts.retries) break;
      await new Promise((r) => setTimeout(r, opts.delay));
    }
    const ok = outcome.tests.every((t) => t.ok);
    failed += ok ? 0 : 1;
    report.push(outcome);
    const retried = outcome.attempt > 1 ? ` (${outcome.attempt} tentativas)` : '';
    console.log(`  ${ok ? 'ok   ' : 'FALHA'}  [${folder}] ${item.name}${retried}`);
    for (const t of outcome.tests.filter((x) => !x.ok)) console.log(`           ${t.name}: ${t.error}`);

    if (opts.payAfter && item.name.includes(opts.payAfter)) {
      const res = await fetch(`${vars().baseUrl}/__e2e/pay/${vars().serviceOrderId}`, { method: 'POST' });
      console.log(`  ${res.ok ? 'ok   ' : 'FALHA'}  pagamento no Mercado Pago falso (webhook assinado): ${res.status}`);
      failed += res.ok ? 0 : 1;
    }
  }
  const total = report.length;
  console.log(`\n${total - failed} de ${total} requisições ok`);
  if (opts.json) fs.writeFileSync(opts.json, JSON.stringify(report, null, 2));
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
