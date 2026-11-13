"""Accélère le thème sv-ttk (style Windows 11) sans rien changer à son apparence.

Le thème dessine champs, boutons, cadres et onglets avec de très petites images « 9 tranches »
(centre de 10 pixels de côté) que Tk répète pour remplir l'élément : un champ de saisie demande
des dizaines de petits tracés, un grand cadre des centaines. Sur un onglet chargé, chaque
changement d'onglet ou redimensionnement coûtait plusieurs centaines de millisecondes.

Le correctif : pendant le chargement du thème, chaque image extensible est remplacée par une
version plus grande, obtenue par la même répétition (donc identique au pixel près une fois
dessinée) ; Tk n'a alors plus que quelques tracés à faire par élément. La taille minimale de
chaque élément reste celle de l'image d'origine (-width / -height).

Usage (main.py) :
    with fast_theme.accelerated(root):
        sv_ttk.set_theme("light")
En cas d'échec, le thème normal est chargé tel quel : ce module ne peut que rendre plus rapide.
"""
from __future__ import annotations

from contextlib import contextmanager

_TCL = r"""
namespace eval ::fasttheme {
    variable cache
    array set cache {}
}

# Image agrandie par répétition des 9 tranches (coins inchangés, bords et centre répétés un
# nombre entier de fois : le rendu final est exactement celui de l'image d'origine).
proc ::fasttheme::enlarge {img bl bt br bb tw th} {
    variable cache
    set key "$img,$bl,$bt,$br,$bb"
    if {[info exists cache($key)]} { return $cache($key) }
    set w [image width $img]
    set h [image height $img]
    set cw [expr {$w - $bl - $br}]
    set ch [expr {$h - $bt - $bb}]
    set kx 1
    set ky 1
    if {$cw > 0} { set kx [expr {max(1, int(ceil(double($tw) / $cw)))}] }
    if {$ch > 0} { set ky [expr {max(1, int(ceil(double($th) / $ch)))}] }
    if {$cw <= 0 || $ch <= 0 || ($kx == 1 && $ky == 1)} {
        set cache($key) $img
        return $img
    }
    set W [expr {$bl + $cw * $kx + $br}]
    set H [expr {$bt + $ch * $ky + $bb}]
    set new [image create photo -width $W -height $H]
    set sx [list 0 $bl [expr {$w - $br}] $w]
    set dx [list 0 $bl [expr {$W - $br}] $W]
    set sy [list 0 $bt [expr {$h - $bb}] $h]
    set dy [list 0 $bt [expr {$H - $bb}] $H]
    for {set i 0} {$i < 3} {incr i} {
        for {set j 0} {$j < 3} {incr j} {
            set x0 [lindex $sx $i]; set x1 [lindex $sx [expr {$i + 1}]]
            set y0 [lindex $sy $j]; set y1 [lindex $sy [expr {$j + 1}]]
            if {$x1 <= $x0 || $y1 <= $y0} { continue }
            $new copy $img -from $x0 $y0 $x1 $y1 \
                -to [lindex $dx $i] [lindex $dy $j] [lindex $dx [expr {$i + 1}]] [lindex $dy [expr {$j + 1}]] \
                -compositingrule set
        }
    }
    set cache($key) $new
    return $new
}

# "element create NOM image SPEC ?options?" -> même commande avec des images agrandies.
proc ::fasttheme::rewrite {argv} {
    set spec [lindex $argv 4]
    set opts [lrange $argv 5 end]
    if {[llength $opts] % 2 || [llength $spec] % 2 == 0} { return $argv }
    array set o $opts
    if {![info exists o(-border)]} { return $argv }
    set b $o(-border)
    switch [llength $b] {
        1 { lassign [list $b $b $b $b] bl bt br bb }
        2 { lassign [list [lindex $b 0] [lindex $b 1] [lindex $b 0] [lindex $b 1]] bl bt br bb }
        4 { lassign $b bl bt br bb }
        default { return $argv }
    }
    set first [lindex $spec 0]
    set w [image width $first]
    set h [image height $first]
    # Grands conteneurs (cadres, bordure des onglets) : image nettement plus grande.
    if {$w >= 40} { set tw 480; set th 360 } else { set tw 240; set th 60 }
    set newspec [list [::fasttheme::enlarge $first $bl $bt $br $bb $tw $th]]
    foreach {state img} [lrange $spec 1 end] {
        lappend newspec $state [::fasttheme::enlarge $img $bl $bt $br $bb $tw $th]
    }
    if {![info exists o(-width)]} { lappend opts -width $w }
    if {![info exists o(-height)]} { lappend opts -height $h }
    return [concat [lrange $argv 0 3] [list $newspec] $opts]
}

proc ::fasttheme::install {} {
    if {[llength [info commands ::ttk::_fasttheme_style]]} { return }
    rename ::ttk::style ::ttk::_fasttheme_style
    proc ::ttk::style {args} {
        if {[lindex $args 0] eq "element" && [lindex $args 1] eq "create" && [lindex $args 3] eq "image"
                && ![string match *dark* [uplevel 1 {namespace current}]]} {
            if {[catch {::fasttheme::rewrite $args} rewritten] == 0} { set args $rewritten }
        }
        uplevel 1 [linsert $args 0 ::ttk::_fasttheme_style]
    }
}

proc ::fasttheme::uninstall {} {
    if {![llength [info commands ::ttk::_fasttheme_style]]} { return }
    rename ::ttk::style {}
    rename ::ttk::_fasttheme_style ::ttk::style
}
"""


@contextmanager
def accelerated(root):
    """Le thème chargé à l'intérieur du bloc `with` reçoit des images agrandies. Sans effet si le
    thème est déjà chargé (ses éléments sont déjà créés)."""
    installed = False
    try:
        root.tk.eval(_TCL)
        root.tk.eval("::fasttheme::install")
        installed = True
    except Exception:  # noqa: BLE001
        pass  # thème normal, simplement plus lent
    try:
        yield
    finally:
        if installed:
            try:
                root.tk.eval("::fasttheme::uninstall")
            except Exception:  # noqa: BLE001
                pass
