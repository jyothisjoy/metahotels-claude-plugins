<?php
/**
 * Plugin Name: Gevora Performance
 * Description: Site-specific frontend cleanup for gevorahotels.com. Stops loading CSS/JS for Header Footer Elementor, Gum Elementor Addon and ElementsKit header widgets that no page on this site uses (including HFE's three broken /elementor-pro/ stylesheet URLs, which 404 because Pro Elements lives in /pro-elements/). Self-healing: if a page ever renders one of those widgets, its assets are loaded again automatically. Since 1.1.0 it also loads Elementor's small popup-dialog stylesheet with the page, so a popup that opens on a timer no longer scrolls the page to the bottom or shifts the layout.
 * Version: 1.1.0
 * Author: MetaHotels
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/*
 * Handles that are enqueued on every page but whose widgets are not used on this site
 * (verified against all 35 sitemap URLs on 2026-10-09).
 *
 * Kept on purpose:
 * - gum-elementor-addon (style.css): Gum adds style controls to core Button / Icon List /
 *   Accordion widgets, so its CSS stays.
 * - ekit-nav-menu / ekit-core / ekit-menu: the header uses the ElementsKit nav menu.
 */
function gevora_perf_groups() {
	return array(
		// Header Footer Elementor: no HFE templates or widgets exist on the site.
		'hfe'  => array(
			'styles'  => array(
				'hfe-widgets-style',
				'hfe-style',
				'hfe-elementor-icons',
				'hfe-icons-list',                        // duplicate of Elementor's widget-icon-list
				'hfe-social-icons',                      // duplicate of Elementor's widget-social-icons
				'hfe-social-share-icons-brands',
				'hfe-social-share-icons-fontawesome',
				'hfe-nav-menu-icons',
				'hfe-widget-blockquote',                 // 404: /plugins/elementor-pro/... (site uses Pro Elements)
				'hfe-mega-menu',                         // 404
				'hfe-nav-menu-widget',                   // 404
			),
			'scripts' => array(),
		),
		// Gum Elementor Addon: carousel / slideshow / price-table libraries with no Gum widgets on the site.
		'gum'  => array(
			'styles'  => array( 'owl.carousel' ),
			'scripts' => array( 'gum-elementor-addon', 'owl.carousel', 'gum-price-table', 'easing', 'superslides' ),
		),
		// ElementsKit header widgets force-loaded on every page; the site's header does not use them.
		'ekit' => array(
			'styles'  => array( 'ekit-header-search', 'ekit-header-offcanvas', 'ekit-header-info' ),
			'scripts' => array( 'ekit-header-search', 'ekit-header-offcanvas', 'magnific-popup' ),
		),
	);
}

function gevora_perf_is_active() {
	if ( is_admin() || wp_doing_ajax() || ( defined( 'REST_REQUEST' ) && REST_REQUEST ) ) {
		return false;
	}
	// Never interfere with the Elementor editor / preview.
	if ( isset( $_GET['elementor-preview'] ) || isset( $_GET['elementor_library'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
		return false;
	}
	return (bool) apply_filters( 'gevora_perf_enabled', true );
}

// Groups that a rendered widget turned out to need on this request.
$GLOBALS['gevora_perf_needed'] = array();

/**
 * Self-healing: note when a widget from one of the groups actually renders.
 * Widgets render in the body, after the head assets were printed, so anything
 * re-enqueued here is printed in the footer by WordPress.
 */
add_action(
	'elementor/frontend/widget/before_render',
	function ( $widget ) {
		$name  = $widget->get_name();
		$class = get_class( $widget );
		$group = null;
		if ( 0 === strpos( $class, 'HFE\\' ) ) {
			$group = 'hfe';
		} elseif ( 0 === strpos( $name, 'gum_' ) ) {
			$group = 'gum';
		} elseif ( in_array( $name, array( 'elementskit-header-search', 'elementskit-header-offcanvas', 'elementskit-header-info', 'elementskit-video', 'elementskit-team' ), true ) ) {
			$group = 'ekit';
		}
		if ( $group && empty( $GLOBALS['gevora_perf_needed'][ $group ] ) ) {
			$GLOBALS['gevora_perf_needed'][ $group ] = true;
			$g = gevora_perf_groups()[ $group ];
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

function gevora_perf_dequeue() {
	if ( ! gevora_perf_is_active() ) {
		return;
	}
	foreach ( gevora_perf_groups() as $group => $g ) {
		if ( ! empty( $GLOBALS['gevora_perf_needed'][ $group ] ) ) {
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

// Plugins enqueue these at different points (wp_enqueue_scripts, Elementor control
// registration, widget render), so dequeue right before each print.
add_action( 'wp_enqueue_scripts', 'gevora_perf_dequeue', 9999 );
add_action( 'wp_print_styles', 'gevora_perf_dequeue', 1 );
add_action( 'wp_print_scripts', 'gevora_perf_dequeue', 1 );
add_action( 'wp_print_footer_scripts', 'gevora_perf_dequeue', 1 );

/*
 * Popup dialog stylesheet. Elementor adds assets/css/conditionals/dialog.min.css (1.4 KB) to the
 * page only at the moment the first popup opens, and 250 ms later moves the keyboard focus to
 * the popup's close button. Until that stylesheet has arrived the popup is not position:fixed
 * yet: it sits at the very end of the page, so the browser scrolls all the way down to the
 * focused button (the page then stays at the footer) and the whole layout shifts when the
 * stylesheet lands (measured 2026-10-12 on the homepage popup that opens 15 s after load:
 * scroll 0 -> 11,048 px, layout shift 1.0 on mobile). Loading the stylesheet with the page
 * removes both. Same file and URL Elementor itself would request, printed before Elementor's
 * frontend stylesheet, which is where Elementor inserts it.
 */
function gevora_perf_dialog_css() {
	if ( ! gevora_perf_is_active() || ! defined( 'ELEMENTOR_ASSETS_URL' ) || ! defined( 'ELEMENTOR_VERSION' ) ) {
		return;
	}
	if ( ! apply_filters( 'gevora_perf_dialog_css', true ) ) {
		return;
	}
	// A later metahotels-core release has the same feature as a switch; when that is on, leave it to core.
	if ( function_exists( 'metahotels_popup_dialog_css_enabled' ) && metahotels_popup_dialog_css_enabled() ) {
		return;
	}
	$suffix = ( defined( 'SCRIPT_DEBUG' ) && SCRIPT_DEBUG ) ? '' : '.min';
	wp_enqueue_style( 'gevora-perf-e-dialog', ELEMENTOR_ASSETS_URL . 'css/conditionals/dialog' . $suffix . '.css', array(), ELEMENTOR_VERSION );
}
add_action( 'wp_enqueue_scripts', 'gevora_perf_dialog_css', 1 );
