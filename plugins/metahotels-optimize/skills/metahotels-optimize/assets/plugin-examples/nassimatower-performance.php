<?php
/**
 * Plugin Name: Nassima Tower Performance
 * Description: Site-specific frontend speed-ups for nassimatower.com. Preloads the homepage hero image (the background video's fallback image, which is the LCP element) through metahotels-core's hero preload, and serves a 4 KB subset of the Jeg Elementor Kit icon font for the icons this site uses, so the 392 KB full font is only downloaded if a page shows an icon outside the subset. Also lazy-loads CSS background images (carousel slides, gallery tiles, section backgrounds) below the second section of a page, which Elementor only does for new-style containers. The preload follows the hero image if it is changed; the subset switches itself off if a Jeg Kit update ships a different icon font. Needs metahotels-core 2.9.8.6 or newer for the preload.
 * Version: 1.1.0
 * Author: MetaHotels
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/*
 * Icons used on this site (all 115 sitemap URLs, header, footer and popup, 2026-10-10).
 * List with class names: assets/jkiticon-subset.txt. Any other icon still works: the browser
 * falls back to the full Jeg font for code points outside this range.
 */
define( 'NASSIMA_PERF_ICON_RANGE', 'U+E924,U+E925,U+E954,U+E962,U+E96C,U+EDF3,U+EE1D,U+EF36,U+EFBE,U+F815,U+F833,U+F847,U+F873,U+F874,U+F94A,U+F9AE,U+F9C5,U+FA12,U+FA9A,U+FB46,U+FBBA' );

// Size of the Jeg Elementor Kit 3.1.0 jkiticon.woff2 the subset was cut from. If a Jeg update
// ships a different font, code points may have moved, so the subset is not used.
define( 'NASSIMA_PERF_ICON_SOURCE_BYTES', 401140 );

function nassima_perf_is_active() {
	if ( is_admin() || wp_doing_ajax() || ( defined( 'REST_REQUEST' ) && REST_REQUEST ) ) {
		return false;
	}
	if ( isset( $_GET['elementor-preview'] ) || isset( $_GET['elementor_library'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
		return false;
	}
	return (bool) apply_filters( 'nassima_perf_enabled', true );
}

/*
 * Homepage hero. The first container is a background video whose fallback image is the LCP
 * element; it is painted from CSS, so the browser finds it late. metahotels-core's "Preload
 * Hero Background Image" (2.9.8.6+) prints the preload tag but, up to 2.9.8.7, only knows
 * classic and slideshow backgrounds. Until a release handles video backgrounds, switch the
 * feature on for the front page and hand it the fallback image. Once it finds the image
 * itself, this adds nothing.
 */
function nassima_perf_hero_enabled( $enabled, $post_id = 0 ) {
	if ( nassima_perf_is_active() && is_front_page() ) {
		return true;
	}
	return $enabled;
}
add_filter( 'metahotels_hero_preload_enabled', 'nassima_perf_hero_enabled', 10, 2 );

function nassima_perf_hero_images( $images, $post_id = 0, $element = array() ) {
	if ( ! empty( $images ) || ! is_front_page() || ! nassima_perf_is_active() ) {
		return $images;
	}
	$settings = ( is_array( $element ) && isset( $element['settings'] ) && is_array( $element['settings'] ) ) ? $element['settings'] : array();
	if ( ! isset( $settings['background_background'] ) || 'video' !== $settings['background_background'] ) {
		return $images;
	}
	if ( empty( $settings['background_video_fallback'] ) || ! is_array( $settings['background_video_fallback'] ) || ! empty( $settings['__dynamic__']['background_video_fallback'] ) ) {
		return $images;
	}
	// Same URL Elementor writes into the CSS: full-size attachment, else the stored URL.
	$fallback = $settings['background_video_fallback'];
	$url      = ! empty( $fallback['id'] ) ? wp_get_attachment_image_url( (int) $fallback['id'], 'full' ) : ( isset( $fallback['url'] ) ? $fallback['url'] : '' );
	if ( ! is_string( $url ) || '' === $url ) {
		return $images;
	}
	return array(
		array(
			'url'   => $url,
			'media' => '',
		),
	);
}
add_filter( 'metahotels_hero_preload_images', 'nassima_perf_hero_images', 10, 3 );

function nassima_perf_icon_subset_css() {
	static $css = null;
	if ( null !== $css ) {
		return $css;
	}
	$css    = '';
	$subset = __DIR__ . '/assets/jkiticon-subset.woff2';
	$source = WP_PLUGIN_DIR . '/jeg-elementor-kit/assets/fonts/jkiticon/jkiticon.woff2';
	if ( ! is_readable( $subset ) || ! is_readable( $source ) || NASSIMA_PERF_ICON_SOURCE_BYTES !== filesize( $source ) ) {
		return $css;
	}
	$css = sprintf(
		'@font-face{font-family:jkiticon;src:url(%s) format("woff2");font-weight:400;font-style:normal;font-display:swap;unicode-range:%s}',
		esc_url( plugins_url( 'assets/jkiticon-subset.woff2', __FILE__ ) . '?ver=' . filemtime( $subset ) ),
		NASSIMA_PERF_ICON_RANGE
	);
	return $css;
}

// Printed right after Jeg's own stylesheet: for the same family the later @font-face wins for
// the code points in its unicode-range, and the full font stays as the fallback for the rest.
function nassima_perf_icon_subset( $tag, $handle ) {
	if ( 'elementor-icons-jkiticon' !== $handle || ! nassima_perf_is_active() ) {
		return $tag;
	}
	$css = nassima_perf_icon_subset_css();
	if ( '' === $css ) {
		return $tag;
	}
	return $tag . '<style id="nassima-perf-jkiticon-subset">' . $css . "</style>\n";
}
add_filter( 'style_loader_tag', 'nassima_perf_icon_subset', 10, 2 );

/*
 * Lazy background images. Elementor's own "Lazy Load Background Images" only covers new-style
 * containers; most pages here are built with classic sections, and Media Carousel slides and Jeg
 * gallery tiles are CSS backgrounds, so every one of them was downloaded on page load (2.9 MB on
 * the homepage). From the third top-level element of a page on, backgrounds stay off until the
 * element is within 800 px of the viewport. Elements near the viewport and elements with a
 * background video or slideshow are switched on straight away, before Elementor starts.
 */
define( 'NASSIMA_PERF_LAZY_BG_SELECTOR', '[data-elementor-type="wp-page"]>.elementor-element~.elementor-element~.elementor-element' );

function nassima_perf_lazy_bg_active() {
	return nassima_perf_is_active() && is_singular( 'page' ) && (bool) apply_filters( 'nassima_perf_lazy_bg', true );
}

function nassima_perf_lazy_bg_css() {
	if ( ! nassima_perf_lazy_bg_active() ) {
		return;
	}
	// The rule only applies once this script has run, so without JavaScript nothing is hidden.
	$sel = '.np-js ' . NASSIMA_PERF_LAZY_BG_SELECTOR . ':not(.np-bg-in)';
	echo '<script id="nassima-perf-lazy-bg-flag">document.documentElement.classList.add("np-js")</script>' . "\n";
	echo '<style id="nassima-perf-lazy-bg">' . $sel . ',' . $sel . ' *{background-image:none!important}</style>' . "\n"; // phpcs:ignore WordPress.Security.EscapeOutput
}
add_action( 'wp_head', 'nassima_perf_lazy_bg_css', 20 );

function nassima_perf_lazy_bg_js() {
	if ( ! nassima_perf_lazy_bg_active() ) {
		return;
	}
	?>
<script id="nassima-perf-lazy-bg-js">
(function () {
	var els = document.querySelectorAll('<?php echo NASSIMA_PERF_LAZY_BG_SELECTOR; // phpcs:ignore WordPress.Security.EscapeOutput ?>');
	if (!els.length) { return; }
	function show(e) { e.classList.add('np-bg-in'); }
	function all() { for (var i = 0; i < els.length; i++) { show(els[i]); } }
	if (!('IntersectionObserver' in window)) { all(); return; }
	var io = new IntersectionObserver(function (entries) {
		for (var i = 0; i < entries.length; i++) {
			if (entries[i].isIntersecting) { show(entries[i].target); io.unobserve(entries[i].target); }
		}
	}, { rootMargin: '800px 0px 800px 0px' });
	var vh = window.innerHeight || 800, moving = /background_video|background_slideshow/;
	for (var i = 0; i < els.length; i++) {
		var e = els[i], r = e.getBoundingClientRect();
		if ((r.top < vh + 800 && r.bottom > -800) || moving.test(e.getAttribute('data-settings') || '') || e.querySelector('[data-settings*="background_video"],[data-settings*="background_slideshow"]')) {
			show(e);
		} else {
			io.observe(e);
		}
	}
	window.addEventListener('beforeprint', all);
})();
</script>
	<?php
}
add_action( 'wp_footer', 'nassima_perf_lazy_bg_js', 5 );
