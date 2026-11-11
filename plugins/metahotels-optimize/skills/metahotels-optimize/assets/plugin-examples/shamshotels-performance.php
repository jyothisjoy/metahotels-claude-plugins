<?php
/**
 * Plugin Name: Shams Hotels Performance
 * Description: Site-specific frontend speed-ups for shamshotels.com. Stops loading the Gum Elementor Addon carousel, slideshow and price-table libraries that no page on this site uses (self-healing: if a page ever renders a Gum widget, they load again). Serves a 2 KB subset of the ElementsKit icon font for the 14 icons this site uses, so the 454 KB full font is only downloaded if a page shows an icon outside the subset (the subset switches itself off if an ElementsKit update ships a different font). Loads Elementor's small popup-dialog stylesheet with the page, so a popup that opens on a timer no longer shifts the layout or scrolls the page to the bottom. Starts the entrance animation of the header and of the first section of each page at first paint instead of when Elementor's script has loaded, so the logo, menu and hero heading are not missing for seconds on a phone.
 * Version: 1.0.0
 * Author: MetaHotels
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/*
 * Icons used on this site (all 347 sitemap URLs with their headers, footers and popups, 2026-10-13).
 * List with class names: assets/elementskit-subset.txt. Any other icon still works: the browser
 * falls back to the full ElementsKit font for code points outside this range.
 */
define( 'SHAMS_PERF_ICON_RANGE', 'U+E870,U+E949,U+E969,U+E973,U+E982,U+E994,U+E9C3,U+E9C5,U+E9F7,U+EA07,U+EA72,U+EB23,U+EB43,U+EB45' );

// Size of the ElementsKit Lite 4.0.8 elementskit.woff the subset was cut from. If an update
// ships a different font, code points may have moved, so the subset is not used.
define( 'SHAMS_PERF_ICON_SOURCE_BYTES', 464672 );

/*
 * Handles that are enqueued on every page but whose widgets are not used on this site
 * (verified against all 347 sitemap URLs on 2026-10-13).
 *
 * Kept on purpose:
 * - gum-elementor-addon (style.css): Gum adds style controls to core Button / Icon List /
 *   Accordion widgets, so its CSS stays.
 * - every ElementsKit asset: the headers use the ElementsKit nav menu, and the heading and
 *   accordion widgets are used on 107 and 24 pages.
 */
function shams_perf_groups() {
	return array(
		// Gum Elementor Addon: carousel / slideshow / price-table libraries with no Gum widgets on the site.
		'gum' => array(
			'styles'  => array( 'owl.carousel' ),
			'scripts' => array( 'gum-elementor-addon', 'owl.carousel', 'gum-price-table', 'easing', 'superslides' ),
		),
	);
}

function shams_perf_is_active() {
	if ( is_admin() || wp_doing_ajax() || ( defined( 'REST_REQUEST' ) && REST_REQUEST ) ) {
		return false;
	}
	// Never interfere with the Elementor editor / preview.
	if ( isset( $_GET['elementor-preview'] ) || isset( $_GET['elementor_library'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
		return false;
	}
	return (bool) apply_filters( 'shams_perf_enabled', true );
}

// Groups that a rendered widget turned out to need on this request.
$GLOBALS['shams_perf_needed'] = array();

/**
 * Self-healing: note when a widget from one of the groups actually renders.
 * Widgets render in the body, after the head assets were printed, so anything
 * re-enqueued here is printed in the footer by WordPress.
 */
add_action(
	'elementor/frontend/widget/before_render',
	function ( $widget ) {
		$group = ( 0 === strpos( $widget->get_name(), 'gum_' ) ) ? 'gum' : null;
		if ( $group && empty( $GLOBALS['shams_perf_needed'][ $group ] ) ) {
			$GLOBALS['shams_perf_needed'][ $group ] = true;
			$g = shams_perf_groups()[ $group ];
			foreach ( $g['styles'] as $h ) {
				if ( wp_style_is( $h, 'registered' ) ) {
					wp_enqueue_style( $h );
				}
			}
			foreach ( $g['scripts'] as $h ) {
				if ( wp_script_is( $h, 'registered' ) ) {
					wp_enqueue_script( $h );
				}
			}
		}
	}
);

function shams_perf_dequeue() {
	if ( ! shams_perf_is_active() ) {
		return;
	}
	foreach ( shams_perf_groups() as $group => $g ) {
		if ( ! empty( $GLOBALS['shams_perf_needed'][ $group ] ) ) {
			continue;
		}
		foreach ( $g['styles'] as $h ) {
			wp_dequeue_style( $h );
		}
		foreach ( $g['scripts'] as $h ) {
			wp_dequeue_script( $h );
		}
	}
}

// Gum enqueues these at different points (wp_enqueue_scripts, Elementor control
// registration), so dequeue right before each print.
add_action( 'wp_enqueue_scripts', 'shams_perf_dequeue', 9999 );
add_action( 'wp_print_styles', 'shams_perf_dequeue', 1 );
add_action( 'wp_print_scripts', 'shams_perf_dequeue', 1 );
add_action( 'wp_print_footer_scripts', 'shams_perf_dequeue', 1 );

function shams_perf_icon_subset_css() {
	static $css = null;
	if ( null !== $css ) {
		return $css;
	}
	$css    = '';
	$subset = __DIR__ . '/assets/elementskit-subset.woff2';
	$source = WP_PLUGIN_DIR . '/elementskit-lite/modules/elementskit-icon-pack/assets/fonts/elementskit.woff';
	if ( ! is_readable( $subset ) || ! is_readable( $source ) || SHAMS_PERF_ICON_SOURCE_BYTES !== filesize( $source ) ) {
		return $css;
	}
	$css = sprintf(
		'@font-face{font-family:elementskit;src:url(%s) format("woff2");font-weight:400;font-style:normal;font-display:swap;unicode-range:%s}',
		esc_url( plugins_url( 'assets/elementskit-subset.woff2', __FILE__ ) . '?ver=' . filemtime( $subset ) ),
		SHAMS_PERF_ICON_RANGE
	);
	return $css;
}

// Printed right after ElementsKit's own icon stylesheet: for the same family the later @font-face
// wins for the code points in its unicode-range, and the full font stays as the fallback for the rest.
function shams_perf_icon_subset( $tag, $handle ) {
	if ( 'elementor-icons-ekiticons' !== $handle || ! shams_perf_is_active() ) {
		return $tag;
	}
	$css = shams_perf_icon_subset_css();
	if ( '' === $css ) {
		return $tag;
	}
	return $tag . '<style id="shams-perf-ekiticons-subset">' . $css . "</style>\n";
}
add_filter( 'style_loader_tag', 'shams_perf_icon_subset', 10, 2 );

/*
 * Entrance animations above the fold. The header row of every header template and the hero text
 * of 159 pages have the "Fade In Up" entrance animation. Elementor hides such elements
 * (.elementor-invisible) until its own JavaScript has loaded and started, so on a phone the logo,
 * the menu and the hero heading were missing for seconds after the page had painted (measured
 * 2026-10-13 on a slow-4G phone: first paint 3 s, heading 6.5 s later even with the chat widget
 * out of the way). For the header and the first section of the page this starts the same
 * animation from CSS at first paint. When Elementor's script arrives it swaps the classes; the
 * animation name stays the same, so it does not play a second time. Everything further down the
 * page keeps animating on scroll as before.
 */
function shams_perf_entrance_css() {
	if ( ! shams_perf_is_active() || ! apply_filters( 'shams_perf_entrance_css', true ) ) {
		return;
	}
	// A later metahotels-core release has the same feature as a switch; when that is on, leave it to core.
	if ( function_exists( 'metahotels_entrance_first_paint_enabled' ) && metahotels_entrance_first_paint_enabled() ) {
		return;
	}
	$scopes = array(
		'.elementor-location-header ',
		'[data-elementor-type="wp-page"]>.elementor-element:first-child ',
		'[data-elementor-type="wp-page"]>.elementor-element:first-child',
		'[data-elementor-type="wp-post"]>.elementor-element:first-child ',
		'[data-elementor-type="wp-post"]>.elementor-element:first-child',
	);
	// Entrance animations in use above the fold on this site; their keyframes come from Elementor's
	// e-animation-<name> stylesheet, which is in the <head> of every page that uses them.
	$names = (array) apply_filters( 'shams_perf_entrance_names', array( 'fadeInUp' ) );
	$css   = '';
	$all   = array();
	foreach ( $names as $name ) {
		if ( ! preg_match( '/^[A-Za-z]+$/', $name ) ) {
			continue;
		}
		$sel = array();
		foreach ( $scopes as $scope ) {
			$sel[] = $scope . '.elementor-invisible[data-settings*=\'animation":"' . $name . '"\']';
		}
		$sel   = implode( ',', $sel );
		$all[] = $sel;
		$css  .= $sel . '{visibility:visible;animation-name:' . $name . ';animation-duration:1.25s}';
	}
	if ( '' === $css ) {
		return;
	}
	echo '<style id="shams-perf-entrance">@media (prefers-reduced-motion:no-preference){' . $css . '}@media (prefers-reduced-motion:reduce){' . implode( ',', $all ) . '{visibility:visible}}</style>' . "\n"; // phpcs:ignore WordPress.Security.EscapeOutput
}
add_action( 'wp_head', 'shams_perf_entrance_css', 20 );

/*
 * Popup dialog stylesheet. Elementor adds assets/css/conditionals/dialog.min.css (1.4 KB) to the
 * page only at the moment the first popup opens, and 250 ms later moves the keyboard focus to
 * the popup's close button. Until that stylesheet has arrived the popup is not position:fixed
 * yet: it sits at the very end of the page, so the whole layout shifts when the stylesheet lands
 * (measured 2026-10-13 on the homepage popup that opens 15 s after load: layout shift 0.29 on
 * desktop, 1.0 on mobile), and on a slow connection the browser scrolls down to the focused
 * button and stays at the footer. Loading the stylesheet with the page removes both. Same file
 * and URL Elementor itself would request, printed before Elementor's frontend stylesheet, which
 * is where Elementor inserts it.
 */
function shams_perf_dialog_css() {
	if ( ! shams_perf_is_active() || ! defined( 'ELEMENTOR_ASSETS_URL' ) || ! defined( 'ELEMENTOR_VERSION' ) ) {
		return;
	}
	if ( ! apply_filters( 'shams_perf_dialog_css', true ) ) {
		return;
	}
	// A later metahotels-core release has the same feature as a switch; when that is on, leave it to core.
	if ( function_exists( 'metahotels_popup_dialog_css_enabled' ) && metahotels_popup_dialog_css_enabled() ) {
		return;
	}
	$suffix = ( defined( 'SCRIPT_DEBUG' ) && SCRIPT_DEBUG ) ? '' : '.min';
	wp_enqueue_style( 'shams-perf-e-dialog', ELEMENTOR_ASSETS_URL . 'css/conditionals/dialog' . $suffix . '.css', array(), ELEMENTOR_VERSION );
}
add_action( 'wp_enqueue_scripts', 'shams_perf_dialog_css', 1 );
