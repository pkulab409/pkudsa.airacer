import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const repoRoot = path.resolve(import.meta.dirname, '../../..');

function loadScript(relativePath, context) {
  const source = fs.readFileSync(path.join(repoRoot, relativePath), 'utf8');
  vm.runInContext(source, context, { filename: relativePath });
}

function createContext() {
  const context = {
    console,
    URLSearchParams,
    TextDecoder,
    location: { search: '' },
    window: { addEventListener() {} },
    document: {
      getElementById() { return null; },
      querySelectorAll() { return []; },
      querySelector() { return null; },
      createElement() { return {}; },
      body: { insertAdjacentHTML() {} },
    },
  };
  return vm.createContext(context);
}

function makeElement() {
  return { innerHTML: '', textContent: '', style: {}, value: '', max: 0, step: 0 };
}

function testLeaderboard() {
  const context = createContext();
  loadScript('frontend/race/leaderboard.js', context);

  assert.equal(context.formatLapTime(null), '—');
  assert.equal(context.formatLapTime(Number.NaN), '—');
  assert.equal(context.formatLapTime(7.4567), '7.456s');
  assert.equal(context.formatLapTime(65.004), '1:05.004');

  const el = makeElement();
  context.updateLeaderboard(el, {
    cars: [
      { team_id: 'slow', lap: 1, lap_progress: 0.9, speed: 9, best_lap_time: 8.5 },
      { team_id: 'fast', lap: 2, lap_progress: 0.1, speed: 5, status: 'finished' },
      { team_id: 'dq', lap: 2, lap_progress: 0.0, speed: 99, status: 'disqualified' },
    ],
  }, [
    { id: 'fast', name: 'Fast Team' },
    { team_id: 'slow', team_name: 'Slow Team' },
    { id: 'dq', name: 'DQ Team' },
  ], { total_laps: 3 });

  assert.match(el.innerHTML, /Fast Team/);
  assert.match(el.innerHTML, /Slow Team/);
  assert.match(el.innerHTML, /DQ Team/);
  assert.match(el.innerHTML, /2\/3/);
  assert.match(el.innerHTML, /status-finished/);
  assert.match(el.innerHTML, /status-dq/);
  assert.match(el.innerHTML, /8.500s/);

  const finalEl = makeElement();
  context.showFinalRankings(finalEl, [
    { team_id: 'fast', rank: 1, total_time: 12.34567 },
    { team_id: 'slow', rank: 2 },
  ], [{ id: 'fast', name: 'Fast Team' }]);

  assert.match(finalEl.innerHTML, /最终排名/);
  assert.match(finalEl.innerHTML, /12.346s/);
  assert.match(finalEl.innerHTML, /未完赛/);
}

function testMinimap() {
  const context = createContext();
  loadScript('frontend/race/minimap.js', context);

  assert.deepEqual(Array.from(context.worldToCanvas(-80, -70, 160, 140)), [0, 140]);
  assert.deepEqual(Array.from(context.worldToCanvas(80, 70, 160, 140)), [160, 0]);
  assert.deepEqual(Array.from(context.worldToCanvas(0, 0, 160, 140)), [80, 70]);
}

function testReplayHelpers() {
  const context = createContext();
  loadScript('frontend/race/leaderboard.js', context);
  loadScript('frontend/race/minimap.js', context);
  loadScript('frontend/race/replay.js', context);

  vm.runInContext('frames = [{ t: 0 }, { t: 1.5 }, { t: 3.0 }];', context);

  assert.equal(context.findFrameIndex(-1), 0);
  assert.equal(context.findFrameIndex(0.5), 0);
  assert.equal(context.findFrameIndex(2.0), 1);
  assert.equal(context.findFrameIndex(3.0), 2);
  assert.equal(context.formatTimeLong(65.349), '01:05.34');
  assert.equal(context.formatTime(65.349), '01:05');
}

testLeaderboard();
testMinimap();
testReplayHelpers();
