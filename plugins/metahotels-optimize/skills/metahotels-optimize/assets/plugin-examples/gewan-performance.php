<?php
/**
 * Plugin Name: Gewan Hotels Performance
 * Description: Site-specific frontend speed-ups for gewanhotels.com. Prints Elementor's small popup stylesheet with the page, so the hotel popups that open on a timer no longer shift the layout or scroll the page to the footer. Lazy-loads CSS background images below the second section of a page until they are near the screen. Stops loading the WP Job Openings (and Pro Pack) styles and scripts on pages that show no job listing or application form. Gives stretched sections on the theme's boxed pages (rooms and default-template pages) their full width from the first paint, and reserves the height of the booking finder in the mobile bottom bar, so neither jumps when the page's scripts run. Sends the "Read More" of the facility cards on each hotel page to that hotel's own facilities page. Each part has its own filter to switch it off.
 * Version: 1.0.1
 * Author: MetaHotels
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

function gewan_perf_is_active() {
	if ( is_admin() || wp_doing_ajax() || ( defined( 'REST_REQUEST' ) && REST_REQUEST ) ) {
		return false;
	}
	if ( isset( $_GET['elementor-preview'] ) || isset( $_GET['elementor_library'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
		return false;
	}
	return (bool) apply_filters( 'gewan_perf_enabled', true );
}

/*
 * Popup stylesheet. Every hotel has a popup that opens 15 s after the page loads. Elementor only
 * adds conditionals/dialog.min.css (1.4 KB) when the first popup opens and focuses the popup's
 * close button 250 ms later. Until the stylesheet arrives the popup sits at the end of the page:
 * the layout shifts when it lands (1.1 on a phone) and on a slow connection the browser scrolls
 * to the focused button. Printed with the page, the popup opens in place.
 */
function gewan_perf_dialog_css() {
	if ( ! gewan_perf_is_active() || ! defined( 'ELEMENTOR_ASSETS_URL' ) || ! defined( 'ELEMENTOR_VERSION' ) ) {
		return;
	}
	if ( ! apply_filters( 'gewan_perf_dialog_css', true ) ) {
		return;
	}
	// A later metahotels-core release has the same feature as a switch; when that is on, leave it to core.
	if ( function_exists( 'metahotels_popup_dialog_css_enabled' ) && metahotels_popup_dialog_css_enabled() ) {
		return;
	}
	$suffix = ( defined( 'SCRIPT_DEBUG' ) && SCRIPT_DEBUG ) ? '' : '.min';
	wp_enqueue_style( 'gewan-perf-e-dialog', ELEMENTOR_ASSETS_URL . 'css/conditionals/dialog' . $suffix . '.css', array(), ELEMENTOR_VERSION );
}
add_action( 'wp_enqueue_scripts', 'gewan_perf_dialog_css', 1 );

/*
 * Lazy background images. Elementor's own "Lazy Load Background Images" only covers new-style
 * containers; the homepage and hotel pages also use classic sections, and nested-carousel slides
 * are CSS backgrounds, so every one of them was downloaded on page load (homepage: 4.3 MB of
 * images without scrolling, including a 1.4 MB section background 5,000 px down). From the third
 * top-level element of a page on, backgrounds stay off until the element is within 800 px of the
 * viewport. Elements near the viewport, and elements with a real background video or slideshow,
 * are switched on straight away, before Elementor starts. A "video" background without a video
 * link only shows its fallback image, so it is lazy-loaded like any other background.
 */
define( 'GEWAN_PERF_LAZY_BG_SELECTOR', '[data-elementor-type="wp-page"]>.elementor-element~.elementor-element~.elementor-element' );

function gewan_perf_lazy_bg_active() {
	return gewan_perf_is_active() && is_singular() && (bool) apply_filters( 'gewan_perf_lazy_bg', true );
}

function gewan_perf_lazy_bg_css() {
	if ( ! gewan_perf_lazy_bg_active() ) {
		return;
	}
	// The rule only applies once this script has run, so without JavaScript nothing is hidden.
	$sel = '.gp-js ' . GEWAN_PERF_LAZY_BG_SELECTOR . ':not(.gp-bg-in)';
	echo '<script id="gewan-perf-lazy-bg-flag">document.documentElement.classList.add("gp-js")</script>' . "\n";
	echo '<style id="gewan-perf-lazy-bg">' . $sel . ',' . $sel . ' *{background-image:none!important}</style>' . "\n"; // phpcs:ignore WordPress.Security.EscapeOutput
}
add_action( 'wp_head', 'gewan_perf_lazy_bg_css', 20 );

function gewan_perf_lazy_bg_js() {
	if ( ! gewan_perf_lazy_bg_active() ) {
		return;
	}
	?>
<script id="gewan-perf-lazy-bg-js">
(function () {
	var els = document.querySelectorAll('<?php echo GEWAN_PERF_LAZY_BG_SELECTOR; // phpcs:ignore WordPress.Security.EscapeOutput ?>');
	if (!els.length) { return; }
	function show(e) { e.classList.add('gp-bg-in'); }
	function all() { for (var i = 0; i < els.length; i++) { show(els[i]); } }
	if (!('IntersectionObserver' in window)) { all(); return; }
	var io = new IntersectionObserver(function (entries) {
		for (var i = 0; i < entries.length; i++) {
			if (entries[i].isIntersecting) { show(entries[i].target); io.unobserve(entries[i].target); }
		}
	}, { rootMargin: '800px 0px 800px 0px' });
	var vh = window.innerHeight || 800, moving = /background_video_link|background_slideshow_gallery/;
	for (var i = 0; i < els.length; i++) {
		var e = els[i], r = e.getBoundingClientRect();
		if ((r.top < vh + 800 && r.bottom > -800) || moving.test(e.getAttribute('data-settings') || '') || e.querySelector('[data-settings*="background_video_link"],[data-settings*="background_slideshow_gallery"]')) {
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
add_action( 'wp_footer', 'gewan_perf_lazy_bg_js', 5 );

/*
 * WP Job Openings + Pro Pack load four stylesheets and three scripts (with intl-tel-input) on
 * every page. Only the /careers/ pages with an [awsmjobs] listing and the /jobs/ openings use
 * them. Kept wherever the page's content or Elementor data mentions a job shortcode; if a job
 * shortcode renders anywhere else (a template, a widget), its assets are added back in the footer.
 */
function gewan_perf_jobs_styles() {
	return array( 'awsm-jobs-general', 'awsm-jobs-style', 'awsm-job-pro-country-select', 'awsm-job-pro-style' );
}

function gewan_perf_jobs_scripts() {
	return array( 'awsm-job-scripts', 'awsm-job-pro-country-select', 'awsm-job-pro-scripts' );
}

function gewan_perf_jobs_needed() {
	if ( is_singular( array( 'awsm_job_openings', 'awsm_job_form' ) ) || is_post_type_archive( 'awsm_job_openings' ) || is_tax() ) {
		return true;
	}
	$id = get_queried_object_id();
	if ( ! $id || ! is_singular() ) {
		return true; // Archives and searches: not analysed, leave as they were.
	}
	$content = (string) get_post_field( 'post_content', $id ) . (string) get_post_meta( $id, '_elementor_data', true );
	return false !== strpos( $content, 'awsm' );
}

/*
 * 1.0.1: run just before the head prints its styles and scripts. At wp_enqueue_scripts 100 (1.0.0)
 * the files were enqueued again later in the request (live 15 October: still on all 184 pages).
 */
function gewan_perf_jobs_dequeue() {
	if ( ! empty( $GLOBALS['gewan_perf_jobs_healed'] ) || ! gewan_perf_is_active() || ! apply_filters( 'gewan_perf_jobs_dequeue', true ) || gewan_perf_jobs_needed() ) {
		return;
	}
	foreach ( gewan_perf_jobs_styles() as $h ) {
		wp_dequeue_style( $h );
	}
	foreach ( gewan_perf_jobs_scripts() as $h ) {
		wp_dequeue_script( $h );
	}
	$GLOBALS['gewan_perf_jobs_removed'] = true;
}
add_action( 'wp_enqueue_scripts', 'gewan_perf_jobs_dequeue', PHP_INT_MAX );
add_action( 'wp_print_styles', 'gewan_perf_jobs_dequeue', PHP_INT_MAX );
add_action( 'wp_print_footer_scripts', 'gewan_perf_jobs_dequeue', 1 ); // before late styles and footer scripts print

function gewan_perf_jobs_heal( $output, $tag ) {
	if ( ! empty( $GLOBALS['gewan_perf_jobs_removed'] ) && 0 === strpos( $tag, 'awsm' ) ) {
		$GLOBALS['gewan_perf_jobs_removed'] = false;
		$GLOBALS['gewan_perf_jobs_healed']  = true;
		foreach ( gewan_perf_jobs_styles() as $h ) {
			wp_enqueue_style( $h );
		}
		foreach ( gewan_perf_jobs_scripts() as $h ) {
			wp_enqueue_script( $h );
		}
	}
	return $output;
}
add_filter( 'pre_do_shortcode_tag', 'gewan_perf_jobs_heal', 10, 2 );

/*
 * Stretched sections. Rooms and pages on the theme's default template sit in its 1200 px
 * container (.nd_options_container); Elementor widens their "stretched" sections to the full
 * screen only when its script runs, so they jump after the first paint (desktop layout shift
 * 0.04-0.15 on 141 pages). The same width is given from the start with CSS. margin-left, not
 * left: Elementor measures the section where it is and then sets its own left (0 here) and
 * width, so the final layout is exactly what it was.
 */
function gewan_perf_layout_css() {
	if ( ! gewan_perf_is_active() ) {
		return;
	}
	$css = '';
	if ( apply_filters( 'gewan_perf_stretch_css', true ) ) {
		$css .= '.nd_options_container [data-elementor-type="wp-page"]>.elementor-section-stretched,.nd_options_container [data-elementor-type="wp-post"]>.elementor-section-stretched{width:100vw;margin-left:calc(50% - 50vw)}';
	}
	/*
	 * Mobile bottom bar (Custom Code "BE Mobile"): the Mirai finder inside it is empty until the
	 * booking engine renders and then 58 px tall, so the fixed bar grew from 57 to 115 px. Our
	 * reservation only; the booking engine's snippets and CSS are unchanged.
	 */
	if ( apply_filters( 'gewan_perf_bemobile_reserve', true ) ) {
		$css .= '@media (max-width:766px){.be-mobile [data-mirai-component="finder"]{min-height:58px}}';
	}
	if ( '' !== $css ) {
		echo '<style id="gewan-perf-layout">' . $css . "</style>\n"; // phpcs:ignore WordPress.Security.EscapeOutput
	}
}
add_action( 'wp_head', 'gewan_perf_layout_css', 21 );

/*
 * Facilities cards. The "Read More" button of the facility card (loop item 8560, widget 62b98b9)
 * is shared by every hotel page and holds one fixed link, /facilities/, which shows Gewan Palace's
 * facilities. On a hotel page the button now goes to that hotel's own facilities page
 * (/hotels/<hotel>/facilities/, or /amenities/). Where the hotel has no such page the link is left
 * as it is.
 */
function gewan_perf_hotel_facilities_url() {
	static $url = null;
	if ( null !== $url ) {
		return $url;
	}
	$url = '';
	$id  = get_queried_object_id();
	if ( $id && preg_match( '#^/hotels/([^/]+)/#', (string) wp_parse_url( get_permalink( $id ), PHP_URL_PATH ), $m ) ) {
		foreach ( array( 'facilities', 'amenities' ) as $slug ) { // Royal M Abu Dhabi: /amenities/
			$page = get_page_by_path( 'hotels/' . $m[1] . '/' . $slug );
			if ( $page && 'publish' === $page->post_status ) {
				$url = get_permalink( $page );
				break;
			}
		}
	}
	return $url;
}

function gewan_perf_facilities_link( $content, $widget ) {
	if ( '62b98b9' !== $widget->get_id() || 'button' !== $widget->get_name() || ! gewan_perf_is_active() || ! apply_filters( 'gewan_perf_facilities_link', true ) ) {
		return $content;
	}
	$url = gewan_perf_hotel_facilities_url();
	if ( '' === $url ) {
		return $content;
	}
	return preg_replace( '#href="(?:' . preg_quote( home_url(), '#' ) . ')?/facilities/?"#', 'href="' . esc_url( $url ) . '"', $content, 1 );
}
add_filter( 'elementor/widget/render_content', 'gewan_perf_facilities_link', 10, 2 );
