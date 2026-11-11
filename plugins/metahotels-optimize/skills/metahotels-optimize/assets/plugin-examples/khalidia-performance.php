<?php
/**
 * Plugin Name: Khalidia Palace Performance
 * Description: Site-specific frontend speed-ups for khalidiapalace.com. Paints the first slide of a hero background slideshow with the page and preloads it, instead of waiting for the slideshow script (the slideshow takes over as soon as it shows the same slide). Starts the entrance animation of the first section of each page at first paint instead of when Elementor's script has loaded, so the hero heading is not missing for seconds on a phone. Prints the stylesheet of a saved template shown in the hero in the page's head, so the hero does not grow and push the page down after the first paint. Loads Elementor's small popup-dialog stylesheet with the page, so the popup that opens on a timer no longer shifts the layout or scrolls the page to the bottom. Keeps the images right below a full-screen hero from downloading ahead of it. Serves a 0.6 KB subset of the Font Awesome solid font for the one icon this site prints from it (the language switcher's caret), so the 78 KB font is only downloaded if a page shows another Font Awesome font icon. Stops loading the WP Job Openings styles and script on pages that show no job listing, the theme's Owl Carousel and Masonry libraries and Elementor's Font Awesome 4 compatibility files, which no page on this site uses (a page that asks for the libraries while it renders still gets them).
 * Version: 1.1.0
 * Author: MetaHotels
 * Requires at least: 6.0
 * Requires PHP: 7.4
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/*
 * Font Awesome solid icons printed as a font on this site (all 130 sitemap URLs with their headers,
 * footers and popup, 2026-10-13): the caret of the language switcher. List: assets/fa-solid-subset.txt.
 * Any other icon still works: the browser falls back to the full font for code points outside this range.
 */
define( 'KPH_PERF_FA_RANGE', 'U+F0D7' );

// Size of Elementor 4.3.4's fa-solid-900.woff2 the subset was cut from. If an update ships a
// different font, code points may have moved, so the subset is not used.
define( 'KPH_PERF_FA_SOURCE_BYTES', 78196 );

/*
 * Handles that are enqueued on every page but used on few or none
 * (verified against all 130 sitemap URLs on 2026-10-13, audit/inventory.txt).
 *
 * - jobs:  WP Job Openings. Job listing markup exists on /all-jobs/, /jobs/ and the job pages only;
 *          the two stylesheets, the script and 29 KB of inline block CSS were on all 129 pages.
 * - theme: Romancy enqueues Owl Carousel and Masonry everywhere. No page has Owl or Masonry markup
 *          and the theme's script.js does not call them (blocked in a test browser on five page
 *          types: no script error, no pixel changed).
 *
 * They are taken out of the queue before the <head> is printed and never afterwards, so a widget
 * that asks for one of them while the page renders still gets it, printed in the footer, and
 * anything declared as a dependency of another script is printed by WordPress regardless.
 *
 * Kept on purpose: imagesLoaded (Elementor's loop grid calls it), Slick (the theme loads it only
 * with the testimonial widget, 10 pages), the ovaicon and icomoon icon fonts (used on every page).
 */
function kph_perf_groups() {
	return array(
		'jobs'  => array(
			'styles'  => array( 'awsm-jobs-general', 'awsm-jobs-style', 'wp-job-openings-blocks-style' ),
			'scripts' => array( 'awsm-job-scripts' ),
		),
		'theme' => array(
			'styles'  => array( 'carousel' ),
			'scripts' => array( 'carousel', 'masonry' ),
		),
		// Elementor's "Font Awesome 4 Support": a stylesheet and a script in the <head> that map the
		// old "fa fa-..." class names. No page uses such a class. Elementor's setting itself must stay
		// on "Yes": switching it off also removes Font Awesome's main stylesheet, and with it the
		// language switcher's caret (tried and reverted on 2026-10-13).
		'fa4'   => array(
			'styles'  => array( 'font-awesome-4-shim' ),
			'scripts' => array( 'font-awesome-4-shim' ),
		),
	);
}

function kph_perf_is_active() {
	if ( is_admin() || wp_doing_ajax() || ( defined( 'REST_REQUEST' ) && REST_REQUEST ) ) {
		return false;
	}
	// Never interfere with the Elementor editor / preview.
	if ( isset( $_GET['elementor-preview'] ) || isset( $_GET['elementor_library'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification
		return false;
	}
	return (bool) apply_filters( 'kph_perf_enabled', true );
}

// Groups that turned out to be needed on this request.
$GLOBALS['kph_perf_needed'] = array();

/**
 * Does this request show a job listing? Decided before the <head> is printed, so the job
 * stylesheets stay in the <head> on the pages that use them.
 */
function kph_perf_jobs_page() {
	if ( is_singular( 'awsm_job_openings' ) || is_post_type_archive( 'awsm_job_openings' ) ) {
		return true;
	}
	$taxonomies = get_object_taxonomies( 'awsm_job_openings' );
	if ( $taxonomies && is_tax( $taxonomies ) ) {
		return true;
	}
	if ( is_singular() ) {
		$post_id = (int) get_queried_object_id();
		$post    = get_post( $post_id );
		if ( $post && false !== stripos( (string) $post->post_content, 'awsm' ) ) {
			return true;
		}
		// Elementor pages keep their widgets (shortcodes included) in this meta.
		$data = get_post_meta( $post_id, '_elementor_data', true );
		if ( is_string( $data ) && false !== stripos( $data, 'awsm' ) ) {
			return true;
		}
	}
	return false;
}

function kph_perf_need( $group ) {
	if ( ! empty( $GLOBALS['kph_perf_needed'][ $group ] ) ) {
		return;
	}
	$GLOBALS['kph_perf_needed'][ $group ] = true;
	$groups = kph_perf_groups();
	if ( empty( $groups[ $group ] ) ) {
		return;
	}
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

/**
 * Self-healing: a job shortcode or job block rendered somewhere the check above did not see
 * (a template, a popup, a widget area). Its assets are added back; they print in the footer.
 */
add_filter(
	'pre_do_shortcode_tag',
	function ( $output, $tag ) {
		if ( is_string( $tag ) && 0 === strpos( $tag, 'awsm' ) ) {
			kph_perf_need( 'jobs' );
		}
		return $output;
	},
	10,
	2
);
add_filter(
	'render_block',
	function ( $content, $block ) {
		if ( ! empty( $block['blockName'] ) && 0 === strpos( $block['blockName'], 'wp-job-openings/' ) ) {
			kph_perf_need( 'jobs' );
		}
		return $content;
	},
	10,
	2
);

function kph_perf_dequeue() {
	if ( ! kph_perf_is_active() ) {
		return;
	}
	if ( empty( $GLOBALS['kph_perf_needed']['jobs'] ) && did_action( 'wp' ) && kph_perf_jobs_page() ) {
		$GLOBALS['kph_perf_needed']['jobs'] = true;
	}
	foreach ( kph_perf_groups() as $group => $g ) {
		if ( ! empty( $GLOBALS['kph_perf_needed'][ $group ] ) ) {
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

// Before the <head> is printed only (see above): after everything has been enqueued, and again
// right before the head styles and scripts are printed.
add_action( 'wp_enqueue_scripts', 'kph_perf_dequeue', 9999 );
add_action( 'wp_print_styles', 'kph_perf_dequeue', 1 );
add_action( 'wp_print_scripts', 'kph_perf_dequeue', 1 );

/*
 * Hero background slideshow. Elementor paints a background slideshow with Swiper: the first
 * slide's image is requested only after jQuery, Elementor and Swiper have loaded and started, so
 * the hero was the last thing to appear (measured 2026-10-13 on a slow-4G phone: first paint
 * 3.5 s, hero image about 30 s; PageSpeed "resource load delay" 5.6 s). When the first top-level
 * element of the page has a background slideshow, this
 *  - preloads the first slide (the exact URL the slideshow uses, so it is downloaded once), and
 *  - paints that image as an ordinary CSS background of the same element from the first paint.
 * The slideshow then draws the same picture on top of it. 1.5 s after the slideshow shows its
 * first slide the static copy is removed, so it never shows through while slides change.
 * The image follows the slideshow: change slide 1 in Elementor and this changes with it.
 */
/**
 * The first top-level element of the queried Elementor page, as stored, with the page's ID; null
 * when the request is not a singular Elementor page.
 */
function kph_perf_first_element() {
	static $first = false;
	if ( false !== $first ) {
		return $first;
	}
	$first = null;
	if ( ! is_singular() || is_preview() || ! class_exists( '\Elementor\Plugin' ) ) {
		return $first;
	}
	$post_id = (int) get_queried_object_id();
	if ( $post_id <= 0 || post_password_required( $post_id ) ) {
		return $first;
	}
	try {
		$plugin   = \Elementor\Plugin::$instance;
		$document = $plugin->documents->get( $post_id );
		if ( ! is_object( $document ) || ! $document->is_built_with_elementor() ) {
			return $first;
		}
		$elements = $document->get_elements_data();
	} catch ( \Throwable $e ) {
		return $first;
	}
	$element = ( is_array( $elements ) && $elements ) ? reset( $elements ) : null;
	if ( is_array( $element ) && ! empty( $element['id'] ) ) {
		$first = array(
			'post'    => $post_id,
			'element' => $element,
		);
	}
	return $first;
}

function kph_perf_hero_slide() {
	static $hero = false;
	if ( false !== $hero ) {
		return $hero;
	}
	$hero = null;
	$top  = kph_perf_first_element();
	if ( ! $top ) {
		return $hero;
	}
	$post_id = $top['post'];
	$first   = $top['element'];
	if ( empty( $first['settings'] ) || ! is_array( $first['settings'] ) ) {
		return $hero;
	}
	$s = $first['settings'];
	if ( ! isset( $s['background_background'] ) || 'slideshow' !== $s['background_background'] ) {
		return $hero;
	}
	// A gallery filled by a dynamic tag is only known once Elementor renders it.
	if ( ! empty( $s['__dynamic__']['background_slideshow_gallery'] ) ) {
		return $hero;
	}
	// Zooming out starts enlarged; a flat copy underneath would not match the first frame.
	if ( isset( $s['background_slideshow_ken_burns'] ) && 'yes' === $s['background_slideshow_ken_burns']
		&& isset( $s['background_slideshow_ken_burns_zoom_direction'] ) && 'out' === $s['background_slideshow_ken_burns_zoom_direction'] ) {
		return $hero;
	}
	$gallery = isset( $s['background_slideshow_gallery'] ) ? $s['background_slideshow_gallery'] : array();
	$slide   = ( is_array( $gallery ) && $gallery ) ? reset( $gallery ) : null;
	$url     = ( is_array( $slide ) && ! empty( $slide['url'] ) && is_string( $slide['url'] ) ) ? $slide['url'] : '';
	if ( '' === $url || ! preg_match( '/^[A-Za-z0-9]+$/', (string) $first['id'] ) ) {
		return $hero;
	}
	$size     = isset( $s['background_slideshow_background_size'] ) ? (string) $s['background_slideshow_background_size'] : '';
	$position = isset( $s['background_slideshow_background_position'] ) ? (string) $s['background_slideshow_background_position'] : '';
	$hero     = array(
		'post'     => $post_id,
		'id'       => (string) $first['id'],
		'url'      => $url,
		'size'     => in_array( $size, array( 'auto', 'cover', 'contain' ), true ) ? $size : 'cover',
		'position' => preg_match( '/^(top|center|bottom) (left|center|right)$/', $position ) ? $position : 'center center',
	);
	return $hero;
}

function kph_perf_hero_preload() {
	if ( ! kph_perf_is_active() || ! apply_filters( 'kph_perf_hero_slide', true ) ) {
		return;
	}
	// metahotels-core preloads the same image when its own switch is on: one preload is enough.
	if ( get_option( 'metahotels_enable_hero_preload', false ) && function_exists( 'metahotels_hero_preload_print' ) ) {
		return;
	}
	$hero = kph_perf_hero_slide();
	if ( $hero ) {
		echo '<link rel="preload" as="image" href="' . esc_url( $hero['url'] ) . '" fetchpriority="high">' . "\n";
	}
}
add_action( 'wp_head', 'kph_perf_hero_preload', 2 );

function kph_perf_hero_css() {
	if ( ! kph_perf_is_active() || ! apply_filters( 'kph_perf_hero_slide', true ) ) {
		return;
	}
	$hero = kph_perf_hero_slide();
	if ( ! $hero ) {
		return;
	}
	$sel  = '.elementor-' . $hero['post'] . ' .elementor-element.elementor-element-' . $hero['id'];
	$show = '>.elementor-background-slideshow .swiper-slide-active';
	$css  = $sel . '{background-image:url("' . esc_url( $hero['url'] ) . '");background-size:' . $hero['size'] . ';background-position:' . $hero['position'] . ';background-repeat:no-repeat}'
		// Lazy-loaded slides get .swiper-lazy-loaded once their image is in place; others are ready when active.
		. $sel . ':has(' . $show . ' .swiper-lazy-loaded),' . $sel . ':has(' . $show . ':not(:has(.swiper-lazy))){animation:kph-hero-static-off 0s 1.5s forwards}'
		. '@keyframes kph-hero-static-off{to{background-image:none}}';
	echo '<style id="kph-perf-hero">' . $css . '</style>' . "\n"; // phpcs:ignore WordPress.Security.EscapeOutput
}
add_action( 'wp_head', 'kph_perf_hero_css', 20 );

/*
 * Templates inside the hero. On 69 pages (53 English pages with template 7605, 16 Arabic ones with
 * 10196) the hero section shows a saved template through Elementor's Template widget. Elementor
 * enqueues that template's stylesheet only when the widget renders, after the <head> has been
 * printed, so the link lands in the <body> below the hero and arrives after the first paint. Until
 * then the hero has no min-height (65vh): it painted 134 px tall and then grew to 549 px, pushing
 * the page down (measured 2026-10-14 on /rooms-suites/: layout shift 0.46 on a phone, 0.28 on
 * desktop; PageSpeed 0.43 / 0.34). The stylesheets of the templates in the page's first top-level
 * element are enqueued here instead, so they are in the <head>; Elementor remembers that a file
 * was enqueued and does not print it a second time. Templates further down the page are left as
 * they are (below the fold, and every stylesheet in the <head> delays the first paint).
 */
function kph_perf_collect_templates( $elements, &$ids ) {
	foreach ( (array) $elements as $el ) {
		if ( ! is_array( $el ) ) {
			continue;
		}
		if ( isset( $el['widgetType'] ) && 'template' === $el['widgetType'] && ! empty( $el['settings']['template_id'] ) ) {
			$ids[] = (int) $el['settings']['template_id'];
		}
		if ( ! empty( $el['elements'] ) ) {
			kph_perf_collect_templates( $el['elements'], $ids );
		}
	}
}

function kph_perf_hero_template_css() {
	if ( ! kph_perf_is_active() || ! apply_filters( 'kph_perf_hero_template_css', true ) || ! class_exists( '\Elementor\Core\Files\CSS\Post' ) ) {
		return;
	}
	$top = kph_perf_first_element();
	if ( ! $top ) {
		return;
	}
	$ids = array();
	kph_perf_collect_templates( array( $top['element'] ), $ids );
	foreach ( array_unique( array_filter( $ids ) ) as $id ) {
		// Connect Polylang for Elementor shows the template's translation in the current language.
		if ( function_exists( 'pll_get_post' ) ) {
			$translated = (int) pll_get_post( $id );
			if ( $translated > 0 ) {
				$id = $translated;
			}
		}
		if ( 'publish' !== get_post_status( $id ) ) {
			continue;
		}
		try {
			\Elementor\Core\Files\CSS\Post::create( $id )->enqueue();
		} catch ( \Throwable $e ) {
			continue;
		}
	}
}
add_action( 'wp_enqueue_scripts', 'kph_perf_hero_template_css', 20 );

/*
 * Images right below the hero. Elementor's image-loading module (and WordPress without it) assumes
 * the first three images of a page are on screen: they load eagerly and the first large one gets
 * fetchpriority="high". The header's two logos count, so the third is the first image of the
 * content. On a page whose first element is a full-screen slideshow that image is below the fold,
 * and on a phone the 344 KB "welcome" image was downloading at high priority ahead of the hero
 * (measured 2026-10-13: from 1.5 s to 7.0 s on slow 4G). On such pages every content image gets
 * loading="lazy" and none gets the high priority; the hero slide is preloaded instead (above).
 * Runs after Elementor's own filter (priority 10). Header and footer images do not pass through
 * this filter, so the logo is unaffected.
 */
function kph_perf_content_img_lazy( $image ) {
	if ( ! is_string( $image ) || ! kph_perf_is_active() || ! apply_filters( 'kph_perf_hero_slide', true ) || ! kph_perf_hero_slide() ) {
		return $image;
	}
	$image = str_replace( array( ' fetchpriority="high"', " fetchpriority='high'" ), '', $image );
	if ( ! preg_match( '/\sloading=/', $image ) ) {
		$image = preg_replace( '/^<img(?=\s)/', '<img loading="lazy"', $image, 1 );
	}
	return $image;
}
add_filter( 'wp_content_img_tag', 'kph_perf_content_img_lazy', 20 );

/*
 * Font Awesome subset. Elementor's all.min.css declares the solid font (78 KB) and the browser
 * fetches it at the highest priority as soon as one solid icon is on the page; here that is one
 * caret. A second @font-face for the same family and weight, printed right after that stylesheet,
 * wins for the code points in its unicode-range; the full font stays as the fallback for any other.
 * The subset is 0.6 KB, so it is inlined: no request at all.
 */
function kph_perf_fa_subset_css() {
	static $css = null;
	if ( null !== $css ) {
		return $css;
	}
	$css    = '';
	$subset = __DIR__ . '/assets/fa-solid-subset.woff2';
	$source = defined( 'ELEMENTOR_PATH' ) ? ELEMENTOR_PATH . 'assets/lib/font-awesome/webfonts/fa-solid-900.woff2' : '';
	if ( '' === $source || ! is_readable( $subset ) || ! is_readable( $source ) || KPH_PERF_FA_SOURCE_BYTES !== filesize( $source ) ) {
		return $css;
	}
	$data = file_get_contents( $subset ); // phpcs:ignore WordPress.WP.AlternativeFunctions
	if ( false === $data || '' === $data || strlen( $data ) > 4096 ) {
		return $css;
	}
	$css = sprintf(
		'@font-face{font-family:"Font Awesome 5 Free";font-style:normal;font-weight:900;font-display:block;src:url(data:font/woff2;base64,%s) format("woff2");unicode-range:%s}',
		base64_encode( $data ), // phpcs:ignore WordPress.PHP.DiscouragedPHPFunctions
		KPH_PERF_FA_RANGE
	);
	return $css;
}

function kph_perf_fa_subset( $tag, $handle ) {
	if ( 'font-awesome-5-all' !== $handle || ! kph_perf_is_active() || ! apply_filters( 'kph_perf_fa_subset', true ) ) {
		return $tag;
	}
	$css = kph_perf_fa_subset_css();
	if ( '' === $css ) {
		return $tag;
	}
	return $tag . '<style id="kph-perf-fa-subset">' . $css . "</style>\n";
}
add_filter( 'style_loader_tag', 'kph_perf_fa_subset', 10, 2 );

/*
 * Entrance animations above the fold. The hero headings of the five homepages and the heading of
 * the FAQ pages have an entrance animation. Elementor hides such elements (.elementor-invisible)
 * until its own JavaScript has loaded and started, so on a phone the heading was missing for
 * seconds after the page had painted. For the first section of the page this starts the same
 * animation from CSS at first paint, with the element's own speed and per-device setting ("none"
 * on tablet means no animation there, as before). When Elementor's script arrives it swaps the
 * classes; the animation name and duration stay the same, so it does not play a second time.
 * Everything further down the page keeps animating on scroll as before.
 */
function kph_perf_entrance_selector( $scopes, $suffix ) {
	$sel = array();
	foreach ( $scopes as $scope ) {
		$sel[] = $scope . '.elementor-invisible' . $suffix;
	}
	return implode( ',', $sel );
}

function kph_perf_entrance_css() {
	if ( ! kph_perf_is_active() || ! apply_filters( 'kph_perf_entrance_css', true ) ) {
		return;
	}
	// A later metahotels-core release has the same feature as a switch; when that is on, leave it to core.
	if ( function_exists( 'metahotels_entrance_first_paint_enabled' ) && metahotels_entrance_first_paint_enabled() ) {
		return;
	}
	$scopes = array(
		'[data-elementor-type="wp-page"]>.elementor-element:first-child ',
		'[data-elementor-type="wp-page"]>.elementor-element:first-child',
		'[data-elementor-type="wp-post"]>.elementor-element:first-child ',
		'[data-elementor-type="wp-post"]>.elementor-element:first-child',
	);
	// Entrance animations in use above the fold on this site (tools/entrance.py); their keyframes come
	// from Elementor's e-animation-<name> stylesheet, which is in the <head> of every page that uses them.
	$names  = (array) apply_filters( 'kph_perf_entrance_names', array( 'fadeInDown', 'slideInDown', 'fadeInUp' ) );
	$names  = array_values( array_filter( $names, function ( $name ) {
		return is_string( $name ) && preg_match( '/^[A-Za-z]+$/', $name );
	} ) );
	if ( ! $names ) {
		return;
	}
	$base   = '';
	$tablet = kph_perf_entrance_selector( $scopes, '[data-settings*=\'animation_tablet":"none"\']' ) . '{animation-name:none}';
	$mobile = kph_perf_entrance_selector( $scopes, '[data-settings*=\'animation_mobile":"none"\']' ) . '{animation-name:none}';
	foreach ( $names as $name ) {
		$base   .= kph_perf_entrance_selector( $scopes, '[data-settings*=\'animation":"' . $name . '"\']' ) . '{visibility:visible;animation-name:' . $name . ';animation-duration:1.25s}';
		$tablet .= kph_perf_entrance_selector( $scopes, '[data-settings*=\'animation_tablet":"' . $name . '"\']' ) . '{animation-name:' . $name . '}';
		$mobile .= kph_perf_entrance_selector( $scopes, '[data-settings*=\'animation_mobile":"' . $name . '"\']' ) . '{animation-name:' . $name . '}';
	}
	// Same durations as Elementor's .animated-slow / .animated-fast.
	$base .= kph_perf_entrance_selector( $scopes, '.animated-slow' ) . '{animation-duration:2s}';
	$base .= kph_perf_entrance_selector( $scopes, '.animated-fast' ) . '{animation-duration:.75s}';
	$show  = kph_perf_entrance_selector( $scopes, '[data-settings*=\'animation":"\']' ) . '{visibility:visible}';
	echo '<style id="kph-perf-entrance">@media (prefers-reduced-motion:no-preference){' . $base . '@media (max-width:1024px){' . $tablet . '}@media (max-width:767px){' . $mobile . '}}@media (prefers-reduced-motion:reduce){' . $show . '}</style>' . "\n"; // phpcs:ignore WordPress.Security.EscapeOutput
}
add_action( 'wp_head', 'kph_perf_entrance_css', 20 );

/*
 * Popup dialog stylesheet. Elementor adds assets/css/conditionals/dialog.min.css (1.4 KB) to the
 * page only at the moment the first popup opens, and 250 ms later moves the keyboard focus to
 * the popup's close button. Until that stylesheet has arrived the popup is not position:fixed
 * yet: it sits at the very end of the page, so the whole layout shifts when the stylesheet lands,
 * and on a slow connection the browser scrolls down to the focused button and stays at the
 * footer. The site-wide popup here opens 15 s after load. Loading the stylesheet with the page
 * removes both. Same file and URL Elementor itself would request, printed before Elementor's
 * frontend stylesheet, which is where Elementor inserts it.
 */
function kph_perf_dialog_css() {
	if ( ! kph_perf_is_active() || ! defined( 'ELEMENTOR_ASSETS_URL' ) || ! defined( 'ELEMENTOR_VERSION' ) ) {
		return;
	}
	if ( ! apply_filters( 'kph_perf_dialog_css', true ) ) {
		return;
	}
	// A later metahotels-core release has the same feature as a switch; when that is on, leave it to core.
	if ( function_exists( 'metahotels_popup_dialog_css_enabled' ) && metahotels_popup_dialog_css_enabled() ) {
		return;
	}
	$suffix = ( defined( 'SCRIPT_DEBUG' ) && SCRIPT_DEBUG ) ? '' : '.min';
	wp_enqueue_style( 'kph-perf-e-dialog', ELEMENTOR_ASSETS_URL . 'css/conditionals/dialog' . $suffix . '.css', array(), ELEMENTOR_VERSION );
}
add_action( 'wp_enqueue_scripts', 'kph_perf_dialog_css', 1 );
