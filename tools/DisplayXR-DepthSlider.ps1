# Vendored copy of the shared DisplayXR depth slider (the same panel the other
# DisplayXR app integrations dock in their menu bar). Apache-2.0, see LICENSE.
# The DisplayXR 3D module starts it from this folder while 3D is on.
<#
DisplayXR depth slider: a small panel docked in an app's menu bar that sets the
stereo depth of its embedded DisplayXR 3D view live.

  Depth  how strong the 3D is (stereo strength, 100 % = the rig's nominal)
  Focus  the distance that sits on the screen; nearer pops out, farther recedes
  - / +  depth in 25 % steps of the nominal; Reset returns to the starting values

It talks to the runtime only through two properties on the app's main window
(needs the dev runtime with DisplayXR #2350):
  DXR_HostedDepthRel     written here: strength*1000 | focus_mm << 16, strength
                         relative to the app's own seeded rig (1 = its nominal)
  DXR_HostedDepthRelNow  published by the runtime: the values in effect
                         (clamped to its comfort limits)
(DXR_HostedDepth / DXR_HostedDepthNow are the same with the absolute factor.)

Works for any app whose 3D is embedded by DisplayXR (DXR_HOSTED_WINDOW):
  pwsh -File DisplayXR-DepthSlider.ps1 -Process "Adobe Substance 3D Modeler"
#>
param(
	[string]$Process = "Adobe Substance 3D Modeler",
	# Target this exact process instead (wins over -Process): with several
	# instances of an app, the slider docks on the one that launched it.
	[int]$ProcessId = 0,
	# Gap, in physical px, between the panel's right edge and the app client's
	# right edge (Modeler's "3D active" status sits there).
	[int]$RightGap = 520,
	# Panel top inside the client area, and its height (Modeler's menu bar is 100 px at 300 %).
	[int]$Top = 6,
	[int]$Height = 88,
	# Focus slider range, metres (architecture/exteriors need more than 3 m).
	[double]$FocusMax = 3.0
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class DxrWin {
	[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr GetPropW(IntPtr h, string name);
	[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern bool SetPropW(IntPtr h, string name, IntPtr v);
	[DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
	[DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
	[DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
	[DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
	[DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
	[DllImport("user32.dll")] public static extern IntPtr SetWindowLongPtrW(IntPtr h, int i, IntPtr v);
	[DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint cmd);
	[DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
	public delegate bool EnumProc(IntPtr h, IntPtr l);
	[DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, IntPtr l);
	[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
	[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
	public struct RECT { public int Left, Top, Right, Bottom; }
	public struct POINT { public int X, Y; }
	// True when window a is above window b in the z-order.
	public static bool IsAbove(IntPtr a, IntPtr b) {
		for (IntPtr h = GetWindow(a, 2); h != IntPtr.Zero; h = GetWindow(h, 2)) if (h == b) return true; // GW_HWNDNEXT
		return false;
	}
	// The DisplayXR 3D window embedded in (owned by) host, or zero.
	public static IntPtr Find3D(IntPtr host) {
		IntPtr found = IntPtr.Zero;
		EnumWindows((h, l) => {
			if (GetWindow(h, 4) != host || !IsWindowVisible(h)) return true; // GW_OWNER
			var sb = new StringBuilder(64); GetClassNameW(h, sb, 64);
			if (sb.ToString().StartsWith("DisplayXR")) { found = h; return false; }
			return true;
		}, IntPtr.Zero);
		return found;
	}
}
"@
[System.Windows.Forms.Application]::SetHighDpiMode([System.Windows.Forms.HighDpiMode]::PerMonitorV2) | Out-Null
[System.Windows.Forms.Application]::EnableVisualStyles()

function Get-Host-Window {
	if ($ProcessId -gt 0) {
		$p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }
	} else {
		$p = Get-Process -Name $Process -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
	}
	if ($p) { return [IntPtr]$p.MainWindowHandle } else { return [IntPtr]::Zero }
}

$hostHwnd = [IntPtr]::Zero
for ($i = 0; $i -lt 240 -and $hostHwnd -eq [IntPtr]::Zero; $i++) { $hostHwnd = Get-Host-Window; if ($hostHwnd -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 500 } }
if ($hostHwnd -eq [IntPtr]::Zero) { return }

# Values: strength 0..2 (x 100 %), focus 0.3..3 m. Start from what the runtime publishes.
$state = @{ Strength = 1.0; Focus = 0.0; Sent = [uint64]0; Seeded = $false; Owned = $false; SentAt = [int64]0 }

# --- Look: legible through the lenticular lens (big type, near-white on dark, no hairlines).
$bg = [System.Drawing.Color]::FromArgb(24, 24, 24)
$fg = [System.Drawing.Color]::FromArgb(240, 240, 240)
$dim = [System.Drawing.Color]::FromArgb(150, 150, 150)
$accent = [System.Drawing.Color]::FromArgb(46, 170, 120)
$font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Regular)
$fontB = New-Object System.Drawing.Font("Segoe UI Semibold", 11, [System.Drawing.FontStyle]::Bold)

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = 'None'; $form.ShowInTaskbar = $false; $form.BackColor = $bg
$form.StartPosition = 'Manual'; $form.AutoScaleMode = 'None'; $form.Text = 'DisplayXR depth'
$form.MinimumSize = New-Object System.Drawing.Size(1, 1)  # allow a short strip (Height below the default minimum)
$form.Size = New-Object System.Drawing.Size(1300, $Height)

# A slider drawn by hand: thick track, large knob, value text; drag or wheel to change.
function New-Slider([string]$name, [double]$min, [double]$max, [scriptblock]$fmt, [scriptblock]$get, [scriptblock]$set, [int]$x) {
	$pn = New-Object System.Windows.Forms.Panel
	$pn.Location = New-Object System.Drawing.Point($x, 0); $pn.Size = New-Object System.Drawing.Size(640, $Height)
	$pn.BackColor = $bg; $pn.Cursor = [System.Windows.Forms.Cursors]::Hand
	$pn.GetType().GetProperty('DoubleBuffered', [Reflection.BindingFlags]'NonPublic,Instance').SetValue($pn, $true)
	$meta = @{ Name = $name; Min = $min; Max = $max; Fmt = $fmt; Get = $get; Set = $set; TrackX = 190; TrackW = 250 }
	$pn.Tag = $meta
	$pn.Add_Paint({
		param($s, $e)
		$m = $s.Tag; $g = $e.Graphics; $g.SmoothingMode = 'AntiAlias'
		$h = $s.Height; $cy = [int]($h / 2)
		$sf = New-Object System.Drawing.StringFormat; $sf.LineAlignment = 'Center'
		$g.DrawString($m.Name, $fontB, (New-Object System.Drawing.SolidBrush $fg), (New-Object System.Drawing.RectangleF(8, 0, ($m.TrackX - 30), $h)), $sf)
		# Doubles throughout: [Math]::Min(1, 0.5) would pick the Int32 overload and give 0.
		$v = [double](& $m.Get); $t = ($v - $m.Min) / ($m.Max - $m.Min); $t = [Math]::Max([double]0, [Math]::Min([double]1, $t))
		$x0 = $m.TrackX; $w = $m.TrackW; $kx = $x0 + [int]($t * $w)
		$g.FillRectangle((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(80, 80, 80))), $x0, $cy - 5, $w, 10)
		$g.FillRectangle((New-Object System.Drawing.SolidBrush $accent), $x0, $cy - 5, $kx - $x0, 10)
		$g.FillEllipse((New-Object System.Drawing.SolidBrush $fg), $kx - 16, $cy - 16, 32, 32)
		$g.DrawString((& $m.Fmt $v), $font, (New-Object System.Drawing.SolidBrush $fg), (New-Object System.Drawing.RectangleF(($x0 + $w + 30), 0, ($s.Width - $x0 - $w - 30), $h)), $sf)
	})
	# Handlers stay plain script blocks (no GetNewClosure): a closure's module scope
	# cannot see this script's functions, so Send-Depth would silently not run.
	$pn.Add_MouseDown({ param($s, $e) Set-FromMouse $s $e.X; $s.Capture = $true })
	$pn.Add_MouseMove({ param($s, $e) if ($e.Button -eq 'Left') { Set-FromMouse $s $e.X } })
	$pn.Add_MouseWheel({
		param($s, $e)
		$m = $s.Tag; $step = ($m.Max - $m.Min) / 40.0
		$v = [double](& $m.Get) + [Math]::Sign($e.Delta) * $step
		& $m.Set ([Math]::Max($m.Min, [Math]::Min($m.Max, $v))); $s.Invalidate(); Send-Depth
	})
	return $pn
}

function Set-FromMouse($s, [int]$mx) {
	$m = $s.Tag; $t = [double]($mx - $m.TrackX) / $m.TrackW; $t = [Math]::Max([double]0, [Math]::Min([double]1, $t))
	& $m.Set ($m.Min + $t * ($m.Max - $m.Min)); $s.Invalidate(); Send-Depth
}

function Send-Depth {
	$s = [uint64][Math]::Round($state.Strength * 1000)
	$f = [uint64][Math]::Round($state.Focus * 1000)
	if ($s -lt 1) { $s = 1 }   # 0 would mean "leave alone"
	$packed = ($s -band 0xFFFF) -bor (($f -band 0xFFFF) -shl 16)
	if ($packed -ne $state.Sent) {
		$state.Sent = $packed; $state.SentAt = [Environment]::TickCount64
		[DxrWin]::SetPropW($hostHwnd, "DXR_HostedDepthRel", [IntPtr][int64]$packed) | Out-Null
	}
}

$depth = New-Slider "Depth" 0.0 2.0 { param($v) "{0:0} %" -f ($v * 100) } { $state.Strength } { param($v) $state.Strength = $v } 0
$focus = New-Slider "Focus" 0.3 $FocusMax { param($v) if ($v -le 0) { "auto" } else { "{0:0.00} m" -f $v } } { $state.Focus } { param($v) $state.Focus = $v } 650
$form.Controls.Add($depth); $form.Controls.Add($focus)

# Depth - / + in 25 % steps of the app's nominal, and Reset (the same controls in every DisplayXR app).
$start = @{}
function Step-Depth([double]$d) {
	$v = [Math]::Round(($state.Strength + $d) * 4) / 4
	$state.Strength = [Math]::Max([double]0.25, [Math]::Min([double]2, $v)); Send-Depth; $depth.Invalidate()
}
function Reset-Depth {
	if ($start.ContainsKey('Strength')) { $state.Strength = $start.Strength; $state.Focus = $start.Focus } else { $state.Strength = 1.0 }
	Send-Depth; $depth.Invalidate(); $focus.Invalidate()
}
function New-Button([string]$text, [int]$x, [int]$w, [scriptblock]$click) {
	$b = New-Object System.Windows.Forms.Button
	$b.Text = $text; $b.Font = $fontB; $b.ForeColor = $fg; $b.BackColor = [System.Drawing.Color]::FromArgb(56, 56, 56)
	$b.FlatStyle = 'Flat'; $b.FlatAppearance.BorderSize = 0; $b.TabStop = $false
	$b.Location = New-Object System.Drawing.Point($x, 8); $b.Size = New-Object System.Drawing.Size($w, ($Height - 16))
	$b.Add_Click($click); $form.Controls.Add($b)
}
$form.Width = 1300 + 330
New-Button "-" 1300 70 { Step-Depth -0.25 }
New-Button "+" 1380 70 { Step-Depth 0.25 }
New-Button "Reset" 1460 150 { Reset-Depth }

# Double-click the panel background = back to the starting values.
$form.Add_DoubleClick({ Reset-Depth })

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 250
$timer.Add_Tick({
	if (-not [DxrWin]::IsWindow($hostHwnd)) { $form.Close(); return }
	$three = [DxrWin]::Find3D($hostHwnd)
	if ($three -eq [IntPtr]::Zero -or [DxrWin]::IsIconic($hostHwnd)) { if ($form.Visible) { $form.Hide() }; return }
	if (-not $state.Seeded) {
		$now = [uint64][int64][DxrWin]::GetPropW($hostHwnd, "DXR_HostedDepthRelNow")
		if ($now -ne 0) {
			$state.Strength = ($now -band 0xFFFF) / 1000.0
			$state.Focus = (($now -shr 16) -band 0xFFFF) / 1000.0
			$start.Strength = $state.Strength; $start.Focus = $state.Focus
			$state.Seeded = $true; $depth.Invalidate(); $focus.Invalidate()
		}
	}
	elseif ([System.Windows.Forms.Control]::MouseButtons -eq 'None' -and [Environment]::TickCount64 - $state.SentAt -gt 800) {
		# (The runtime applies a change on its 250 ms poll; give it time before reading back.)
		# Show what is in effect: the runtime clamps strength to its comfort limit.
		$now = [uint64][int64][DxrWin]::GetPropW($hostHwnd, "DXR_HostedDepthRelNow")
		$ns = ($now -band 0xFFFF) / 1000.0; $nf = (($now -shr 16) -band 0xFFFF) / 1000.0
		if ($now -ne 0 -and ([Math]::Abs($ns - $state.Strength) -gt 0.005 -or [Math]::Abs($nf - $state.Focus) -gt 0.005)) {
			$state.Strength = $ns; $state.Focus = $nf; $depth.Invalidate(); $focus.Invalidate()
		}
	}
	# Dock: inside the host's client area, top right, left of its status.
	$rc = New-Object DxrWin+RECT; $pt = New-Object DxrWin+POINT
	[DxrWin]::GetClientRect($hostHwnd, [ref]$rc) | Out-Null; [DxrWin]::ClientToScreen($hostHwnd, [ref]$pt) | Out-Null
	$x = $pt.X + $rc.Right - $RightGap - $form.Width; $y = $pt.Y + $Top
	if (-not $state.Owned) {
		# Owned by the app: stays above it, minimizes with it, no taskbar entry.
		[DxrWin]::SetWindowLongPtrW($form.Handle, -8, $hostHwnd) | Out-Null; $state.Owned = $true
	}
	if (-not $form.Visible) { $form.Show() }
	# The 3D window is owned by the same host, so it can end up over the panel (e.g. after
	# the host is restored): lift the panel back above it without taking focus.
	if (-not [DxrWin]::IsAbove($form.Handle, $three)) { [DxrWin]::SetWindowPos($form.Handle, [IntPtr]::Zero, 0, 0, 0, 0, 0x0001 -bor 0x0002 -bor 0x0010) | Out-Null }
	if ($form.Left -ne $x -or $form.Top -ne $y) { [DxrWin]::SetWindowPos($form.Handle, [IntPtr]::Zero, $x, $y, 0, 0, 0x0001 -bor 0x0004 -bor 0x0010) | Out-Null }
})
$timer.Start()
$form.Add_Shown({ $form.Hide() })
[System.Windows.Forms.Application]::Run($form)
