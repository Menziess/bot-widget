// The Bot Widget face on a canvas: the same shape, springs and poses as botwidget/avatar.py and animation.py.
(function () {
  var SIZE = 68, R = 29, C = 34;
  var PARALLAX = 0.35, GAZE_NEAR = R * 2, ON_FACE = R * 1.1;
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
    lift: [500, 0.60], lean: [220, 0.32], sx: [260, 0.30], sy: [260, 0.30]
  };
  var REST = { dx: 0, dy: 0, scale: 1, converge: 0, happy: 0, lift: 0, lean: 0, sx: 1, sy: 1 };
  var SETTLED = { dx: 0.04, dy: 0.04, converge: 0.04, lift: 0.04, lean: 0.04, scale: 0.004, happy: 0.004, sx: 0.004, sy: 0.004 };
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
    rest: [0, 0, 1.0], idle: [7.1, -3.7, 1.0], look: [0, 2, 1.0], blink: [null, null, 0.0], read0: [-2, 1, 1.0], read1: [2, 1, 1.0], turn1: [3.1, -7.4, 1.0], turn2: [1.6, -3.1, 1.0], turn3: [7.8, 1.6, 1.0], front: [0.0, 0.0, 1.0], turn5: [-4.4, 0.1, 1.0], turn6: [2.9, 0.5, 1.0], turn7: [-7.1, -3.8, 1.0], turn8: [-7.3, -3.3, 1.0], turn9: [6.3, 4.9, 1.0], turn10: [1.7, 7.8, 1.0], turn11: [6.0, -5.3, 1.0]
  };
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

  function silhouette() {
    var pts = RADII.map(function (r, i) {
      var a = i / 64 * 2 * Math.PI;
      return [C + Math.cos(a) * r * R, C + Math.sin(a) * r * R];
    });
    var path = new Path2D(), n = pts.length, k = 1 / 6;
    path.moveTo(pts[0][0], pts[0][1]);
    for (var i = 0; i < n; i++) {
      var a = pts[(i - 1 + n) % n], o = pts[i], s = pts[(i + 1) % n], c = pts[(i + 2) % n];
      path.bezierCurveTo(o[0] + (s[0] - a[0]) * k, o[1] + (s[1] - a[1]) * k,
                         s[0] - (c[0] - o[0]) * k, s[1] - (c[1] - o[1]) * k, s[0], s[1]);
    }
    path.closePath();
    return { path: path, min: C - 1.15 * R, size: 2 * 1.15 * R };
  }
  var HEAD = silhouette();

  function lerp(a, b, t) { return a + (b - a) * t; }
  // A Grok Bot blink presses the pill to a lying one of 0.42 its width.
  function lid(length, width, scale) {
    return scale >= 1 ? length * scale : lerp(length, 0.42 * width, 1 - Math.max(0, scale));
  }

  // One eye is a thick line with round ends: a standing or lying pill that grows into a ^ when happy.
  function eye(ctx, ex, ey, ew, eh, tilt, happy, color, alpha, arc) {
    var half = Math.max(0.01, Math.abs(eh - ew) / 2), pill, thick;
    if (eh >= ew) { pill = [[ex, ey - half], [ex, ey], [ex, ey + half]]; thick = ew; }
    else { pill = [[ex - half, ey], [ex, ey], [ex + half, ey]]; thick = eh; }
    // Grok Bot's happy eye: an arc as thick as the eye.
    var size = ew * arc, top = ey - 0.577 * size, foot = ey + 0.04 * size;
    var caret = [[ex - 0.615 * size, foot], [ex, 2 * top - foot], [ex + 0.615 * size, foot]];
    var m = pill.map(function (p, i) { return [lerp(p[0], caret[i][0], happy), lerp(p[1], caret[i][1], happy)]; });
    ctx.save();
    ctx.translate(ex, ey); ctx.rotate(tilt * (1 - happy) * DEG); ctx.translate(-ex, -ey);
    ctx.globalAlpha = alpha; ctx.strokeStyle = color; ctx.lineCap = "round";
    ctx.lineWidth = lerp(thick, size, happy);
    ctx.beginPath(); ctx.moveTo(m[0][0], m[0][1]); ctx.quadraticCurveTo(m[1][0], m[1][1], m[2][0], m[2][1]);
    ctx.stroke();
    ctx.restore();
  }

  function gradient(ctx, cx, cy, r, stops) {
    var g = ctx.createRadialGradient(HEAD.min + cx * HEAD.size, HEAD.min + cy * HEAD.size, 0,
                                     HEAD.min + cx * HEAD.size, HEAD.min + cy * HEAD.size, r * HEAD.size);
    stops.forEach(function (s) { g.addColorStop(s[0], s[1]); });
    return g;
  }

  // Draws the face with its top left at (pad, pad) face units; k is device pixels per face unit.
  function draw(ctx, v, k, pad) {
    var P = PARALLAX, apart = Math.sin(BOT.split * DEG) * R;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.setTransform(k, 0, 0, k, pad * k, pad * k);
    ctx.save();
    ctx.translate(v.dx * P, v.dy * P - v.lift);
    ctx.translate(C, C); ctx.rotate((BOT.tilt + v.lean) * DEG); ctx.scale(v.sx, v.sy); ctx.translate(-C, -C);
    ctx.fillStyle = BOT.hex; ctx.fill(HEAD.path);
    ctx.fillStyle = gradient(ctx, 0.62, 0.68, 0.75, [[0.45, BOT.shade + "00"], [1, BOT.shade + "80"]]); ctx.fill(HEAD.path);
    ctx.fillStyle = gradient(ctx, 0.30, 0.22, 0.80, [[0, "rgba(255,255,255,0.18)"], [0.6, "rgba(255,255,255,0)"]]); ctx.fill(HEAD.path);
    ctx.translate(-v.dx * P, -v.dy * P);
    for (var i = 0; i < 2; i++) {
      var e = BOT.eyes[i], side = i === 0 ? -1 : 1;
      var ex = C + side * apart + (i === 0 ? v.converge : -v.converge) + v.dx, ey = C + v.dy;
      var ew = Math.max(2, e[0] * R), eh = Math.max(2, lid(e[1] * R * e[3], ew, v.scale));
      // Grok Bot's two happy arcs take 0.93 of the distance between the eyes, so they never touch.
      var widest = Math.max(2, Math.max(BOT.eyes[0][0], BOT.eyes[1][0]) * R) * (2 * 0.615 + 1);
      var arc = Math.min(1, 0.93 * 2 * apart / widest);
      eye(ctx, ex, ey + 1.3, ew, eh, e[2], v.happy, "#000", 0.14, arc);
      eye(ctx, ex, ey, ew, eh, e[2], v.happy, EYE_FILL, 1, arc);
    }
    ctx.restore();
  }

  window.BotFace = { SIZE: SIZE, R: R, GAZE_NEAR: GAZE_NEAR, Animator: Animator, POSES: POSES, CYCLE: CYCLE, gaze: gaze, draw: draw };
})();
