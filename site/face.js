// The Bot Widget face on a canvas: the same shape, springs and poses as botwidget/avatar.py and animation.py,
// drawn as a 3D body like botwidget/body3d.py: a turn turns its outline and shading, and the eyes lie on
// its surface, so they bend and foreshorten with it.
(function () {
  var SIZE = 68, R = 29, C = 34;
  var GAZE_NEAR = R * 2, ON_FACE = R * 1.1;
  var DEG = Math.PI / 180;

  // The squircle repeats every quarter turn; 64 radii around the circle, angle 0 at 3 o'clock.
  var QUARTER = [0.9591, 0.9637, 0.9776, 1.0007, 1.0321, 1.0696, 1.108, 1.1383, 1.15, 1.1383, 1.108, 1.0696, 1.0321, 1.0007, 0.9776, 0.9637];
  var RADII = [];
  for (var i = 0; i < 64; i++) RADII.push(QUARTER[i % 16]);

  var BOT = {
    hex: "#1cc3b0", shade: "#108376", tilt: -9.6,
    split: 16, eyes: [[0.22, 0.4, -28, 1], [0.22, 0.4, 28, 1]]
  };
  var EYE_FILL = "#f9f9f9";

  // stiffness, damping. Below 1 a property overshoots a little: that gives the wobble.
  var SPRINGS = {
    dx: [320, 0.80], dy: [320, 0.80], scale: [900, 0.90], converge: [320, 0.90], happy: [400, 0.90],
    lift: [500, 0.60], lean: [220, 0.32], sx: [260, 0.30], sy: [260, 0.30], zoom: [6, 1.0]
  };
  var REST = { dx: 0, dy: 0, scale: 1, converge: 0, happy: 0, lift: 0, lean: 0, sx: 1, sy: 1, zoom: 1 };
  var SETTLED = { dx: 0.04, dy: 0.04, converge: 0.04, lift: 0.04, lean: 0.04, scale: 0.004, happy: 0.004, sx: 0.004, sy: 0.004, zoom: 0.002 };
  var MAX_STEP = 1 / 30, SUBSTEP = 0.008;

  function Animator() {
    this.value = {}; this.velocity = {}; this.target = {};
    for (var name in REST) { this.value[name] = this.target[name] = REST[name]; this.velocity[name] = 0; }
  }
  Animator.prototype.aim = function (targets) {
    for (var name in targets) {
      if (!(name in this.target)) throw new Error("unknown " + name);
      this.target[name] = targets[name];
    }
  };
  Animator.prototype.kick = function (name, speed) { this.velocity[name] += speed; };
  Animator.prototype.step = function (dt) {
    dt = Math.min(dt, MAX_STEP);
    var pieces = Math.max(1, Math.ceil(dt / SUBSTEP));
    for (var p = 0; p < pieces; p++) {
      for (var name in SPRINGS) {
        var s = SPRINGS[name], x = this.value[name], v = this.velocity[name];
        v += (s[0] * (this.target[name] - x) - 2 * s[1] * Math.sqrt(s[0]) * v) * (dt / pieces);
        this.value[name] = x + v * (dt / pieces);
        this.velocity[name] = v;
      }
    }
    var moving = false;
    for (var n in SPRINGS) {
      if (Math.abs(this.target[n] - this.value[n]) < SETTLED[n] && Math.abs(this.velocity[n]) < SETTLED[n] * 10) {
        this.value[n] = this.target[n]; this.velocity[n] = 0;
      } else moving = true;
    }
    return moving;
  };

  // dx, dy, length factor; a blink (null) keeps the eyes where they look. Generated from avatar.py:
  // Grok Bot's idle clips, their head turns and blinks.
  var POSES = {
    rest: [0, 0, 1.0], idle: [15.3, -7.9, 1.0], look: [0, 2, 1.0], blink: [null, null, 0.0], read0: [-2, 1, 1.0], read1: [2, 1, 1.0], turn1: [7.0, -16.3, 1.0], turn2: [1.6, -3.1, 1.0], turn3: [18.6, 3.8, 1.0], turn5: [-4.4, 0.1, 1.0], turn6: [2.9, 0.5, 1.0], turn7: [-15.1, -8.0, 1.0], turn8: [-14.8, -6.8, 1.0], turn9: [6.7, 5.2, 1.0], turn10: [2.5, 11.2, 1.0], turn11: [13.9, -12.2, 1.0], front: [0.0, 0.0, 1.0]
  };
  // Grok Bot's Idle_B breathes: [ms into the idle loop, size], from avatar.py.
  var BREATH = [[6000, 1.0667], [7610, 1.0000], [16000, 1.0667], [17610, 1.0000], [20000, 1.0667], [21610, 1.0000]], BREATH_LOOP = 24000;
  function breathAt(ms) {
    ms %= BREATH_LOOP;
    var goal = 1;
    BREATH.forEach(function (b) { if (b[0] <= ms) goal = b[1]; });
    return goal;
  }
  var CYCLE = {
    idle: [["turn1", 590], ["blink", 130], ["turn2", 1240], ["turn3", 110], ["blink", 130], ["turn3", 170], ["blink", 130], ["turn3", 1410], ["idle", 340], ["blink", 130], ["idle", 1620], ["front", 900], ["turn5", 580], ["blink", 130], ["turn5", 10], ["turn6", 870], ["front", 970], ["blink", 130], ["front", 410], ["front", 490], ["turn7", 670], ["blink", 130], ["turn7", 90], ["turn8", 400], ["turn9", 970], ["turn10", 180], ["turn11", 1070], ["blink", 130], ["front", 1920], ["front", 900], ["turn5", 580], ["blink", 130], ["turn5", 10], ["turn6", 870], ["front", 970], ["blink", 130], ["front", 410], ["front", 900], ["turn5", 580], ["blink", 130], ["turn5", 10], ["turn6", 870], ["front", 970], ["blink", 130], ["front", 410]],
    work: [["read0", 280], ["read1", 280], ["read0", 280], ["blink", 120]]
  };

  // Where the eyes look when the pointer is at (vx, vy) from the face centre, in face units.
  // Over the face itself they look straight out at you; close by they follow and squint a little.
  // Unlike the app, which only follows a pointer this near, the page keeps following from afar.
  function gaze(vx, vy) {
    var dist = Math.hypot(vx, vy);
    if (dist <= ON_FACE) return { dx: 0, dy: 0, converge: 0, scale: 1 };
    var t = Math.max(0, 1 - dist / GAZE_NEAR), close = t * t * t, look = dist < GAZE_NEAR ? Math.sqrt(t) : 1;
    return {
      dx: Math.max(-8, Math.min(8, vx / dist * 8 * Math.max(look, 0.6))),
      dy: Math.max(-8, Math.min(8, vy / dist * 8 * Math.max(look, 0.6))),
      converge: close * 6, scale: 1 - close * 0.4
    };
  }

  // ── The body in 3D (botwidget/body3d.py) ──────────────────────────────
  var DEPTH = 0.8, SLICES = 11, DENSE = 384, BINS = 128, LOFT = 0.72;
  function turn(pitch, yaw) {
    var cp = Math.cos(pitch * DEG), sp = Math.sin(pitch * DEG), cy = Math.cos(yaw * DEG), sy = Math.sin(yaw * DEG);
    return function (x, y, z) {
      var y2 = y * cp + z * sp, z2 = z * cp - y * sp;
      return [x * cy + z2 * sy, y2, z2 * cy - x * sy];
    };
  }
  function anglesFor(dx, dy) {
    var pitch = Math.asin(Math.max(-1, Math.min(1, dy / R))) / DEG;
    var yaw = Math.asin(Math.max(-1, Math.min(1, dx / (R * Math.cos(pitch * DEG))))) / DEG;
    return [pitch, yaw];
  }
  var BASE = RADII.map(function (r, i) { var a = i / 64 * 2 * Math.PI; return [Math.cos(a) * r, Math.sin(a) * r]; });
  function densify(points, count) {
    var lengths = points.map(function (p, i) { var q = points[(i + 1) % points.length]; return Math.hypot(q[0] - p[0], q[1] - p[1]); });
    var total = lengths.reduce(function (a, b) { return a + b; }, 0) || 1, out = [], at = 0, k = 0;
    for (var i = 0; i < count; i++) {
      var want = total * i / count;
      while (k < points.length - 1 && at + lengths[k] < want) { at += lengths[k]; k++; }
      var a = points[k], b = points[(k + 1) % points.length], t = lengths[k] ? (want - at) / lengths[k] : 0;
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
    return out;
  }
  var DENSE_BASE = densify(BASE, DENSE), OUTLINES = {}, OUTLINE_COUNT = 0;
  // The outline of the lofted body, turned: the outermost point in each direction, softened.
  function outline(pitch, yaw) {
    if (!pitch && !yaw) return BASE;
    var key = pitch + "," + yaw;
    if (OUTLINES[key]) return OUTLINES[key];
    var rot = turn(pitch, yaw), best = [];
    for (var s = 0; s < SLICES; s++) {
      var a = -Math.PI / 2 + Math.PI * s / (SLICES - 1), sc = Math.pow(Math.max(0, Math.cos(a)), LOFT), z = DEPTH * Math.sin(a);
      for (var i = 0; i < DENSE; i++) {
        var p = rot(DENSE_BASE[i][0] * sc, DENSE_BASE[i][1] * sc, z), r = Math.hypot(p[0], p[1]);
        var k = Math.floor(((Math.atan2(p[1], p[0]) + 2 * Math.PI) % (2 * Math.PI)) / (2 * Math.PI) * BINS) % BINS;
        if (!best[k] || r > best[k][0]) best[k] = [r, p[0], p[1]];
      }
    }
    var filled = best.filter(Boolean), n = filled.length, W = [[-2, 1], [-1, 2], [0, 3], [1, 2], [2, 1]];
    var out = filled.map(function (b, i) {
      var soft = W.reduce(function (acc, w) { return acc + w[1] * filled[(i + w[0] + n) % n][0]; }, 0) / 9;
      return [b[1] * soft / b[0], b[2] * soft / b[0]];
    });
    if (++OUTLINE_COUNT > 4096) { OUTLINES = {}; OUTLINE_COUNT = 0; }
    return (OUTLINES[key] = radiiOf(out, 64));
  }
  // Back to 64 radii at even angles, as points again.
  function radiiOf(points, count) {
    var polar = points.map(function (p) { return [(Math.atan2(p[1], p[0]) + 2 * Math.PI) % (2 * Math.PI), Math.hypot(p[0], p[1])]; })
      .sort(function (a, b) { return a[0] - b[0]; });
    polar = [[polar[polar.length - 1][0] - 2 * Math.PI, polar[polar.length - 1][1]]].concat(polar, [[polar[0][0] + 2 * Math.PI, polar[0][1]]]);
    var out = [], j = 0;
    for (var i = 0; i < count; i++) {
      var want = i / count * 2 * Math.PI;
      while (j < polar.length - 2 && polar[j + 1][0] < want) j++;
      var a = polar[j], b = polar[j + 1], t = b[0] > a[0] ? (want - a[0]) / (b[0] - a[0]) : 0, r = a[1] + (b[1] - a[1]) * t;
      out.push([Math.cos(want) * r, Math.sin(want) * r]);
    }
    return out;
  }
  function bodyPath(points) {
    var pts = points.map(function (p) { return [C + p[0] * R, C + p[1] * R]; });
    var path = new Path2D(), n = pts.length, k = 1 / 6;
    path.moveTo(pts[0][0], pts[0][1]);
    for (var i = 0; i < n; i++) {
      var a = pts[(i - 1 + n) % n], o = pts[i], s = pts[(i + 1) % n], c = pts[(i + 2) % n];
      path.bezierCurveTo(o[0] + (s[0] - a[0]) * k, o[1] + (s[1] - a[1]) * k,
                         s[0] - (c[0] - o[0]) * k, s[1] - (c[1] - o[1]) * k, s[0], s[1]);
    }
    path.closePath();
    return path;
  }
  var HEAD = { min: C - 1.15 * R, size: 2 * 1.15 * R };

  function lerp(a, b, t) { return a + (b - a) * t; }
  // A Grok Bot blink presses the pill to a lying one of 0.42 its width.
  function lid(length, width, scale) {
    return scale >= 1 ? length * scale : lerp(length, 0.42 * width, 1 - Math.max(0, scale));
  }

  // The outline of a thick line with round ends, around a polyline.
  function stroke(line, half) {
    var caps = 7, normals = line.map(function (p, i) {
      var a = line[Math.max(0, i - 1)], b = line[Math.min(line.length - 1, i + 1)], tx = b[0] - a[0], ty = b[1] - a[1], n = Math.hypot(tx, ty) || 1;
      return [-ty / n, tx / n];
    });
    function cap(c, nrm) {
      var base = Math.atan2(nrm[1], nrm[0]), out = [];
      for (var k = 1; k < caps; k++) out.push([c[0] + Math.cos(base - Math.PI * k / caps) * half, c[1] + Math.sin(base - Math.PI * k / caps) * half]);
      return out;
    }
    var left = line.map(function (p, i) { return [p[0] + normals[i][0] * half, p[1] + normals[i][1] * half]; });
    var right = line.map(function (p, i) { return [p[0] - normals[i][0] * half, p[1] - normals[i][1] * half]; });
    var last = line.length - 1;
    return left.concat(cap(line[last], normals[last]), right.reverse(), cap(line[0], [-normals[0][0], -normals[0][1]]));
  }
  // One eye, flat, around its middle (head radii): a pill that blinks into a lying one and smiles into
  // Grok Bot's happy arc, as thick as the eye.
  function eyeShape(w, h, tilt, happy, scale, arc) {
    var min = 2 / R, ew = Math.max(min, w), eh = Math.max(min, lid(h, ew, scale)), half = Math.max(0.001, Math.abs(eh - ew) / 2), pill, thick;
    if (eh >= ew) { pill = [[0, -half], [0, 0], [0, half]]; thick = ew; }
    else { pill = [[-half, 0], [0, 0], [half, 0]]; thick = eh; }
    var size = ew * arc, top = -0.577 * size, foot = 0.04 * size;
    var caret = [[-0.615 * size, foot], [0, 2 * top - foot], [0.615 * size, foot]];
    var m = pill.map(function (p, i) { return [lerp(p[0], caret[i][0], happy), lerp(p[1], caret[i][1], happy)]; });
    var t = tilt * (1 - happy) * DEG, c = Math.cos(t), sn = Math.sin(t), line = [];
    for (var k = 0; k < 9; k++) {
      var q = k / 8, x = (1 - q) * (1 - q) * m[0][0] + 2 * (1 - q) * q * m[1][0] + q * q * m[2][0];
      var y = (1 - q) * (1 - q) * m[0][1] + 2 * (1 - q) * q * m[1][1] + q * q * m[2][1];
      line.push([x * c - y * sn, x * sn + y * c]);
    }
    return stroke(line, lerp(thick, size, happy) / 2);
  }
  // Lay a flat eye on the unit sphere at centre, turned: it bends with the surface. null when turned away.
  function onSurface(centre, shape, rot) {
    var n = Math.hypot(centre[0], centre[2]) || 1, rx = centre[2] / n, rz = -centre[0] / n, front = 0;
    var out = shape.map(function (p) {
      var x = centre[0] + p[0] * rx, y = centre[1] + p[1], z = centre[2] + p[0] * rz, k = 1 / (Math.hypot(x, y, z) || 1);
      var q = rot(x * k, y * k, z * k);
      front += q[2];
      return q;
    });
    return front > 0 ? out : null;
  }

  function gradient(ctx, cx, cy, r, stops) {
    var g = ctx.createRadialGradient(HEAD.min + cx * HEAD.size, HEAD.min + cy * HEAD.size, 0,
                                     HEAD.min + cx * HEAD.size, HEAD.min + cy * HEAD.size, r * HEAD.size);
    stops.forEach(function (s) { g.addColorStop(s[0], s[1]); });
    return g;
  }

  // Draws the face with its top left at (pad, pad) face units; k is device pixels per face unit.
  function draw(ctx, v, k, pad) {
    var ang = anglesFor(v.dx, v.dy), pitch = Math.round(ang[0] * 2) / 2, yaw = Math.round(ang[1] * 2) / 2;
    var rot = turn(ang[0], ang[1]), head = bodyPath(outline(pitch, yaw)), lit = rot(0, 0, DEPTH);
    var sx = lit[0] * 0.45, sy = lit[1] * 0.45;  // the shading turns with the body, as in avatar.py
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.setTransform(k, 0, 0, k, pad * k, pad * k);
    ctx.save();
    ctx.translate(0, -v.lift);
    ctx.translate(C, C); ctx.rotate((BOT.tilt + v.lean) * DEG); ctx.scale(v.sx * v.zoom, v.sy * v.zoom); ctx.translate(-C, -C);
    ctx.fillStyle = BOT.hex; ctx.fill(head);
    ctx.fillStyle = gradient(ctx, 0.62 + sx, 0.68 + sy, 0.75, [[0.45, BOT.shade + "00"], [1, BOT.shade + "80"]]); ctx.fill(head);
    ctx.fillStyle = gradient(ctx, 0.30 + sx, 0.22 + sy, 0.80, [[0, "rgba(255,255,255,0.18)"], [0.6, "rgba(255,255,255,0)"]]); ctx.fill(head);
    ctx.clip(head);
    var across = Math.sin(BOT.split * DEG);
    // Grok Bot's two happy arcs take 0.93 of the distance between the eyes, so they never touch.
    var widest = Math.max(2 / R, Math.max(BOT.eyes[0][0], BOT.eyes[1][0])) * (2 * 0.615 + 1);
    var arc = Math.min(1, 0.93 * 2 * across / widest);
    ctx.fillStyle = EYE_FILL;
    for (var i = 0; i < 2; i++) {
      var e = BOT.eyes[i], x = (i === 0 ? -across : across) + (i === 0 ? v.converge : -v.converge) / R;
      var laid = onSurface([x, 0, Math.sqrt(Math.max(0, 1 - x * x))], eyeShape(e[0], e[1] * e[3], e[2], v.happy, v.scale, arc), rot);
      if (!laid) continue;
      ctx.beginPath();
      laid.forEach(function (p, j) { if (j) ctx.lineTo(C + p[0] * R, C + p[1] * R); else ctx.moveTo(C + p[0] * R, C + p[1] * R); });
      ctx.closePath(); ctx.fill();
    }
    ctx.restore();
  }

  window.BotFace = { SIZE: SIZE, R: R, GAZE_NEAR: GAZE_NEAR, Animator: Animator, POSES: POSES, CYCLE: CYCLE, gaze: gaze, draw: draw, breathAt: breathAt };
})();
