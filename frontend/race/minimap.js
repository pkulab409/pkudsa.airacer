// minimap.js — track_complex layout
const TEAM_COLORS = ['#ef4444','#3b82f6','#22c55e','#f59e0b','#a855f7','#06b6d4'];

// World bounds derived from track_complex.wbt geometry + telemetry data
const WORLD = { xMin: -50, xMax: 210, yMin: -35, yMax: 165 };

function worldToCanvas(x, y, W, H) {
  const cx = (x - WORLD.xMin) / (WORLD.xMax - WORLD.xMin) * W;
  const cy = (1 - (y - WORLD.yMin) / (WORLD.yMax - WORLD.yMin)) * H;
  return [cx, cy];
}

// ── Track centerline waypoints for track_complex ──────────────────────────
// Derived from track_complex.wbt road segment positions + telemetry car path
const TRACK_CENTER = [
  // main straight (west→east, start/finish at x≈56)
  {x: -11, y: -29},
  {x: 20,  y: -29},
  {x: 56,  y: -29},   // start/finish line
  {x: 100, y: -29.3},
  {x: 140, y: -29.4},
  {x: 179, y: -29.5},

  // T1 SE corner (right turn into east straight)
  {x: 190, y: -25},
  {x: 196, y: -18},
  {x: 199, y: -10},

  // east straight (south→north)
  {x: 199, y: 30},
  {x: 199, y: 70},
  {x: 199, y: 110},
  {x: 199, y: 136},

  // NE curve (turning left → west)
  {x: 196, y: 148},
  {x: 185, y: 157},
  {x: 170, y: 160},

  // upper S-curve complex
  {x: 155, y: 159},
  {x: 140, y: 150},
  {x: 138, y: 140},
  {x: 145, y: 129},
  {x: 158, y: 124},
  {x: 171, y: 110},
  {x: 171, y: 98},
  {x: 158, y: 90},
  {x: 140, y: 89},
  {x: 125, y: 93},
  {x: 115, y: 103},
  {x: 110, y: 120},
  {x: 109, y: 141},
  {x: 105, y: 153},
  {x: 95,  y: 158},

  // NW descending straight
  {x: 78,  y: 158},
  {x: 78,  y: 90},
  {x: 79,  y: 50},
  {x: 80,  y: 15},
  {x: 80,  y: -5},

  // NW hairpin turning left, then up
  {x: 70,  y: -7},
  {x: 55,  y: -3},
  {x: 50,  y: 5},
  {x: 49,  y: 25},
  {x: 48,  y: 50},

  // upper NW section
  {x: 47,  y: 80},
  {x: 46,  y: 110},
  {x: 45,  y: 137},
  {x: 35,  y: 148},
  {x: 15,  y: 150},
  {x: -5,  y: 150},

  // western curve + hairpin
  {x: -22, y: 149},
  {x: -35, y: 144},
  {x: -43, y: 132},
  {x: -44, y: 118},
  {x: -38, y: 107},
  {x: -25, y: 100},
  {x: -10, y: 98},
  {x: -1,  y: 95},
  {x: 8,   y: 90},
  {x: 14,  y: 78},
  {x: 16,  y: 65},
  {x: 13,  y: 54},
  {x: 3,   y: 47},
  {x: -10, y: 43},
  {x: -25, y: 36},
  {x: -31, y: 22},
  {x: -32, y: 8},
  {x: -29, y: -8},
  {x: -23, y: -21},
  {x: -13, y: -27},
  {x: 0,   y: -29},
  {x: 30,  y: -29},
  {x: 48,  y: -28},    // approaching start again
];

// ── Checkpoint positions (for reference, from track_complex.wbt) ──────────
const CHECKPOINTS = [
  {x: 56,  y: -29},    // checkpoint_0 (start/finish)
  {x: 199, y: 0},      // checkpoint_1
  {x: 199, y: 103},    // checkpoint_2
  {x: 158, y: 160},    // checkpoint_3
  {x: 92,  y: 159},    // checkpoint_4
  {x: 47.5,y: 60},     // checkpoint_5
  {x: -5,  y: 150},    // checkpoint_6
  {x: -22, y: 98},     // checkpoint_7
  {x: -18, y: 40},     // checkpoint_8
];

function drawTrackBackground(canvas) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;

  // Dark background
  ctx.fillStyle = '#0d1117';
  ctx.fillRect(0, 0, W, H);

  // Convert track to canvas coords
  const pts = TRACK_CENTER.map(p => {
    const [cx, cy] = worldToCanvas(p.x, p.y, W, H);
    return {x: cx, y: cy};
  });

  // ── Outer curb (red/white kerb) ──
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.lineWidth = 46;
  ctx.strokeStyle = '#3a1515';
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.stroke();

  // ── Track asphalt surface ──
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.lineWidth = 40;
  ctx.strokeStyle = '#1e1e1e';
  ctx.stroke();

  // ── Road surface (darker gray) ──
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.lineWidth = 28;
  ctx.strokeStyle = '#4a4a4a';
  ctx.stroke();

  // ── Dashed center line ──
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
  ctx.lineWidth = 2;
  ctx.strokeStyle = 'rgba(255,255,255,0.3)';
  ctx.setLineDash([6, 10]);
  ctx.stroke();
  ctx.setLineDash([]);

  // ── Direction arrows (every ~12th segment) ──
  for (let i = 0; i < pts.length - 1; i += 12) {
    const a = pts[i], b = pts[i + 1];
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    const angle = Math.atan2(b.y - a.y, b.x - a.x);
    ctx.save();
    ctx.translate(mx, my);
    ctx.rotate(angle);
    ctx.fillStyle = 'rgba(255,255,255,0.25)';
    ctx.beginPath();
    ctx.moveTo(6, 0);
    ctx.lineTo(-4, -4);
    ctx.lineTo(-4, 4);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // ── Start/finish line ──
  const [sfx, sfy] = worldToCanvas(56, -29, W, H);
  // Draw checkered pattern perpendicular to track direction
  const sfAngle = -0.02;  // approximately horizontal at S/F
  ctx.save();
  ctx.translate(sfx, sfy);
  ctx.rotate(sfAngle);
  const sqSize = 4, cols = 9, rows = 2;
  for (let col = 0; col < cols; col++) {
    for (let row = 0; row < rows; row++) {
      ctx.fillStyle = (col + row) % 2 === 0 ? '#fff' : '#000';
      ctx.fillRect(
        -cols * sqSize / 2 + col * sqSize,
        -rows * sqSize / 2 + row * sqSize,
        sqSize, sqSize
      );
    }
  }
  // S/F label above line
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 9px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('S/F', 0, -10);
  ctx.restore();

  // ── Checkpoint markers ──
  CHECKPOINTS.forEach((cp, i) => {
    const [cx, cy] = worldToCanvas(cp.x, cp.y, W, H);
    ctx.beginPath();
    ctx.arc(cx, cy, 4, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0,200,255,0.5)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,200,255,0.8)';
    ctx.lineWidth = 1;
    ctx.stroke();
    // Label
    ctx.fillStyle = 'rgba(0,200,255,0.7)';
    ctx.font = '7px monospace';
    ctx.textAlign = 'left';
    ctx.fillText('C' + i, cx + 6, cy + 3);
  });

  // ── Infield grass patches ──


}

function drawCars(ctx, frame, W, H) {
  if (!frame || !frame.cars) return;
  frame.cars.forEach((car, i) => {
    const [cx, cy] = worldToCanvas(car.x, car.y, W, H);
    const color = (car.status === 'disqualified' || car.status === 'idle') ? '#555' : TEAM_COLORS[i % TEAM_COLORS.length];

    // Shadow
    ctx.beginPath();
    ctx.arc(cx, cy, 9, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0,0,0,0.4)';
    ctx.fill();

    // Glow ring for leader
    if (i === 0) {
      ctx.beginPath();
      ctx.arc(cx, cy, 11, 0, Math.PI * 2);
      ctx.strokeStyle = color + '88';
      ctx.lineWidth = 3;
      ctx.stroke();
    }

    // Car circle
    ctx.beginPath();
    ctx.arc(cx, cy, 7, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Direction arrow (heading: 0=+X, increases CCW)
    // Canvas Y is flipped, so negate heading
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-car.heading + Math.PI / 2);
    ctx.beginPath();
    ctx.moveTo(0, -13);
    ctx.lineTo(4, -7);
    ctx.lineTo(-4, -7);
    ctx.closePath();
    ctx.fillStyle = '#fff';
    ctx.fill();
    ctx.restore();

    // Label with background
    const label = car.team_id;
    ctx.font = 'bold 10px monospace';
    const labelW = ctx.measureText(label).width + 4;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(cx + 10, cy - 8, labelW, 14);
    ctx.fillStyle = color;
    ctx.textAlign = 'left';
    ctx.fillText(label, cx + 12, cy + 4);
  });
}
