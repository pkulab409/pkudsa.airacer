// leaderboard.js
function updateLeaderboard(el, frame, teams, metadata) {
  if (!frame || !frame.cars) return;
  const sorted = [...frame.cars].sort((a, b) => {
    if ((b.checkpoints_passed || 0) !== (a.checkpoints_passed || 0)) return (b.checkpoints_passed || 0) - (a.checkpoints_passed || 0);
    if (b.lap !== a.lap) return b.lap - a.lap;
    if (b.lap_progress !== a.lap_progress) return b.lap_progress - a.lap_progress;
    return (b.speed || 0) - (a.speed || 0);
  });
  const totalLaps = (metadata && metadata.total_laps) ? metadata.total_laps : '?';
  let rows = sorted.map((car, i) => {
    const team = teams.find(t => (t.id || t.team_id) === car.team_id);
    const name = team ? (team.name || team.team_name || car.team_id) : car.team_id;

    let statusBadge = '';
    if (car.status === 'disqualified') {
      statusBadge = '<span class="status-badge status-dq">弃</span>';
    } else if (car.status === 'stopped') {
      statusBadge = '<span class="status-badge status-stopped">停</span>';
    } else if (car.status === 'finished') {
      statusBadge = '<span class="status-badge status-finished">完</span>';
    }

    const speedStr = (car.status === 'disqualified' || car.speed == null)
      ? '—'
      : car.speed.toFixed(1) + ' m/s';

    const cpStr = car.checkpoints_passed != null ? `${car.checkpoints_passed}` : '—';

    const lapStr = car.lap != null ? `${car.lap}/${totalLaps}` : '—';

    const bestLap = car.best_lap_time != null
      ? formatLapTime(car.best_lap_time)
      : '—';

    return `<tr class="${i === 0 ? 'leader' : ''}">
      <td class="lb-rank">${i + 1}</td>
      <td class="lb-name">${name}${statusBadge}</td>
      <td class="lb-lap">${cpStr}</td>
      <td class="lb-lap">${lapStr}</td>
      <td class="lb-best">${bestLap}</td>
      <td class="lb-speed">${speedStr}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div class="lb-header">实时排名</div>
    <table class="lb-table">
      <thead>
        <tr>
          <th>#</th>
          <th>队伍</th>
          <th>检查点</th>
          <th>圈次</th>
          <th>最快圈</th>
          <th>速度</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function showFinalRankings(el, rankings, teams) {
  if (!rankings || !rankings.length) return;
  const medals = ['#FFD700', '#C0C0C0', '#CD7F32'];
  const medalEmoji = ['1st', '2nd', '3rd'];

  let rows = rankings.map(r => {
    const team = teams.find(t => (t.id || t.team_id) === r.team_id);
    const name = team ? (team.name || team.team_name || r.team_id) : r.team_id;
    const time = r.total_time != null ? r.total_time.toFixed(3) + 's' : '未完赛';
    const rankNum = r.rank || (rankings.indexOf(r) + 1);
    const medalColor = medals[rankNum - 1] || '#aaa';
    const rankDisplay = rankNum <= 3
      ? `<span style="color:${medalColor};font-weight:bold">${rankNum}.</span>`
      : `${rankNum}.`;
    return `<tr>
      <td class="lb-rank">${rankDisplay}</td>
      <td class="lb-name">${name}</td>
      <td class="lb-time">${time}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div class="lb-header final-header">
      <span style="font-size:18px">🏁</span> 最终排名
    </div>
    <table class="lb-table">
      <thead>
        <tr>
          <th>#</th>
          <th>队伍</th>
          <th>用时</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function formatLapTime(seconds) {
  if (seconds == null || isNaN(seconds)) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  if (m > 0) {
    return `${m}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
  }
  return `${s}.${String(ms).padStart(3, '0')}s`;
}
