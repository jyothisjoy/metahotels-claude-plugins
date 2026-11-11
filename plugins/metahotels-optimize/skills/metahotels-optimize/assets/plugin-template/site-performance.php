<?php
/**
 * Plugin Name: {Site} Performance
 * Description: Site-specific frontend cleanup. Stops loading CSS/JS for addon widgets that no page on this site uses. Self-healing: if a page ever renders one of those widgets, its assets are loaded again automatically.
 * Version: 1.0.0
 * Author: MetaHotels
 * Requires at least: 6.0
 * Requires PHP: 7.4
 *
 * TEMPLATE — copy to <site-folder>/<site>-performance/<site>-performance.php, rename the
 * `site_perf_` prefix to the site's slug, and keep ONLY the groups/handles that were proven unused
 * on that site (sweep.js widget list + simblock.js pixel diff). Worked examples of every proven technique
 * (dialog CSS, lazy CSS backgrounds, icon-font subsets, entrance CSS, hero slide, late dequeues) are in
 * <skill>/assets/plugin-examples/; references/site-plugin.md says which file holds what.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

function site_perf_groups() {
	return array(
		// Header Footer Elementor — only if the site has NO HFE templates and NO HFE widgets.
		// HFE 2.9.x hardcodes /plugins/elementor-pro/... for the last three, which 404 on Pro Elements sites.
		'hfe'  => array(
			'styles'  => array(
				'hfe-widgets-style', 'hfe-style', 'hfe-elementor-icons', 'hfe-icons-list', 'hfe-social-icons',
				'hfe-social-share-icons-brands', 'hfe-social-share-icons-fontawesome', 'hfe-nav-menu-icons',
				'hfe-widget-blockquote', 'hfe-mega-menu', 'hfe-nav-menu-widget',
			),
			'scripts' => array(),
		),
		// Gum Elementor Addon — only if no gum_* widgets are used. Keep the `gum-elementor-addon` STYLE:
		// Gum adds style controls to core Button / Icon List / Accordion widgets.
		'gum'  => array(
			'styles'  => array( 'owl.carousel' ),
			'scripts' => array( 'gum-elementor-addon', 'owl.carousel', 'gum-price-table', 'easing', 'superslides' ),
		),
		// ElementsKit Lite force-loads header widget assets on every page "in case" a header uses them.
		'ekit' => array(
			'styles'  => array( 'ekit-header-search', 'ekit-header-offcanvas', 'ekit-header-info' ),
			'scripts' => array( 'ekit-header-search', 'ekit-header-offcanvas', 'magnific-popup' ),
		),
	);
}

function site_perf_is_active() {
	if ( is_admin() || wp_doing_ajax() || ( defined( 'REST_REQUEST' ) && REST_REQUEST ) ) {
		return false;
	}
	if ( isset( $_GET['elementor-preview'] ) || isset( $_GET['elementor_library'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
		return false;
	}
	return (bool) apply_filters( 'site_perf_enabled', true );
}

$GLOBALS['site_perf_needed'] = array();

// Self-healing: widgets render in the body after head assets were printed, so anything
// re-enqueued here is printed in the footer by WordPress.
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
		$groups = site_perf_groups();
		if ( $group && isset( $groups[ $group ] ) && empty( $GLOBALS['site_perf_needed'][ $group ] ) ) {
			$GLOBALS['site_perf_needed'][ $group ] = true;
			foreach ( $groups[ $group ]['styles'] as $h ) {
				if ( wp_style_is( $h, 'registered' ) ) {
					wp_enqueue_style( $h );
				}
			}
			foreach ( $groups[ $group ]['scripts'] as $h ) {
				if ( wp_script_is( $h, 'registered' ) ) {
					wp_enqueue_script( $h );
				}
			}
		}
	}
);

function site_perf_dequeue() {
	if ( ! site_perf_is_active() ) {
		return;
	}
	foreach ( site_perf_groups() as $group => $g ) {
		if ( ! empty( $GLOBALS['site_perf_needed'][ $group ] ) ) {
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

// Plugins enqueue at different points (wp_enqueue_scripts, Elementor control registration,
// widget render), so dequeue right before each print.
add_action( 'wp_enqueue_scripts', 'site_perf_dequeue', 9999 );
add_action( 'wp_print_styles', 'site_perf_dequeue', 1 );
add_action( 'wp_print_scripts', 'site_perf_dequeue', 1 );
add_action( 'wp_print_footer_scripts', 'site_perf_dequeue', 1 );
