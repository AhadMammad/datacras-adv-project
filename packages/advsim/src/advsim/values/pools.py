"""Static vocabularies for realistic values (en_US / USD-centric agency)."""
from __future__ import annotations

CURRENCIES = {"USD": 0.84, "EUR": 0.06, "GBP": 0.05, "CAD": 0.03, "AUD": 0.02}
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.66}
COUNTRIES3 = {"USA": 0.82, "CAN": 0.05, "GBR": 0.05, "DEU": 0.02, "FRA": 0.02, "AUS": 0.02, "MEX": 0.02}
COUNTRY2 = {"USA": "US", "CAN": "CA", "GBR": "GB", "DEU": "DE", "FRA": "FR", "AUS": "AU", "MEX": "MX"}

US_GEO = [  # city, state, lat, lon, zip prefix, timezone
    ("New York", "NY", 40.7128, -74.0060, "100", "America/New_York"),
    ("Los Angeles", "CA", 34.0522, -118.2437, "900", "America/Los_Angeles"),
    ("Chicago", "IL", 41.8781, -87.6298, "606", "America/Chicago"),
    ("Houston", "TX", 29.7604, -95.3698, "770", "America/Chicago"),
    ("Phoenix", "AZ", 33.4484, -112.0740, "850", "America/Phoenix"),
    ("Philadelphia", "PA", 39.9526, -75.1652, "191", "America/New_York"),
    ("San Antonio", "TX", 29.4241, -98.4936, "782", "America/Chicago"),
    ("San Diego", "CA", 32.7157, -117.1611, "921", "America/Los_Angeles"),
    ("Dallas", "TX", 32.7767, -96.7970, "752", "America/Chicago"),
    ("Austin", "TX", 30.2672, -97.7431, "787", "America/Chicago"),
    ("Seattle", "WA", 47.6062, -122.3321, "981", "America/Los_Angeles"),
    ("Denver", "CO", 39.7392, -104.9903, "802", "America/Denver"),
    ("Boston", "MA", 42.3601, -71.0589, "021", "America/New_York"),
    ("Atlanta", "GA", 33.7490, -84.3880, "303", "America/New_York"),
    ("Miami", "FL", 25.7617, -80.1918, "331", "America/New_York"),
    ("Minneapolis", "MN", 44.9778, -93.2650, "554", "America/Chicago"),
    ("Portland", "OR", 45.5152, -122.6784, "972", "America/Los_Angeles"),
    ("Nashville", "TN", 36.1627, -86.7816, "372", "America/Chicago"),
    ("Charlotte", "NC", 35.2271, -80.8431, "282", "America/New_York"),
    ("Detroit", "MI", 42.3314, -83.0458, "482", "America/Detroit"),
]
GEO_WEIGHTS = [8, 6, 5, 4, 2, 3, 2, 2, 3, 2, 3, 2, 3, 3, 3, 2, 1, 1, 1, 1]
TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "Europe/London"]

BROWSERS = {"Chrome": 0.63, "Safari": 0.24, "Edge": 0.06, "Firefox": 0.04, "Samsung Internet": 0.03}
OPERATING_SYSTEMS = {"iOS": 0.31, "Android": 0.30, "Windows": 0.25, "macOS": 0.10, "tvOS": 0.02, "Roku OS": 0.02}
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S921U) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/26.0 Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "Roku/DVP-14.0 (14.0.0.4183-46)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
]

IAB_CATEGORIES = ["IAB1", "IAB2", "IAB3", "IAB5", "IAB7", "IAB8", "IAB9", "IAB12", "IAB13", "IAB17", "IAB18",
                  "IAB19", "IAB20", "IAB22"]
CONTENT_CATEGORIES = ["News", "Sports", "Entertainment", "Technology", "Business & Finance", "Lifestyle",
                      "Food & Drink", "Travel", "Health & Fitness", "Automotive", "Home & Garden", "Gaming"]
INDUSTRIES = ["Consumer Packaged Goods", "Retail", "Automotive", "Financial Services", "Telecommunications",
              "Travel & Hospitality", "Pharmaceuticals", "Technology", "Quick Service Restaurants",
              "Entertainment & Media", "Beverages", "Insurance"]

AD_SIZES = ["300x250", "728x90", "160x600", "320x50", "300x600", "970x250", "1920x1080", "1280x720"]
SITE_WORDS = ["daily", "post", "times", "herald", "wire", "hub", "now", "insider", "weekly", "journal",
              "guide", "today", "zone", "beat", "pulse", "report", "digest", "network"]
SITE_TOPICS = ["sports", "tech", "news", "travel", "food", "auto", "money", "style", "health", "home",
               "game", "film", "music", "outdoor", "parent", "pet", "garden", "fitness"]

PRODUCT_WORDS = ["Spark", "Fresh", "Prime", "Bold", "Pure", "Velvet", "Summit", "Harbor", "Nova", "Crest",
                 "Echo", "Glow", "Peak", "Breeze", "Atlas", "Ember", "Orchid", "Ridge", "Lumen", "Juniper"]
PRODUCT_NOUNS = ["Cola", "Bites", "Care", "Motors", "Bank", "Mobile", "Air", "Home", "Kitchen", "Labs",
                 "Wear", "Pets", "Snacks", "Coffee", "Water", "Beauty", "Sports", "Auto Insurance", "Cloud", "Fit"]
CAMPAIGN_THEMES = ["Back to School", "Summer Kickoff", "Holiday", "Spring Refresh", "Brand Relaunch",
                   "New Product Launch", "Always On", "Black Friday", "Q4 Push", "Loyalty Drive",
                   "Retargeting", "Awareness Burst", "Super Bowl Tie-In", "Valentine's Day", "Tax Season",
                   "Memorial Day Sale", "Labor Day Sale", "Game Day", "Fall Favorites", "Year End Clearance"]

DEPARTMENTS = ["Account Management", "Media Planning", "Media Buying", "Programmatic", "Creative",
               "Production", "Strategy", "Analytics", "Finance", "Ad Operations", "Social", "Search"]
JOB_TITLES = ["Account Director", "Account Manager", "Media Planner", "Senior Media Buyer", "Programmatic Trader",
              "Creative Director", "Art Director", "Copywriter", "Producer", "Strategist", "Data Analyst",
              "Ad Ops Specialist", "Finance Manager", "Project Manager", "VP Media", "Group Account Director"]

NOTES = [
    "Client requested weekly performance recap.", "Pending final sign-off from client legal.",
    "Rates confirmed with vendor on call.", "Approved per email thread with account lead.",
    "Budget reallocated from underperforming tactics.", "Awaiting updated creative from production.",
    "Tracking verified in staging.", "Flight dates aligned to client promo calendar.",
    "Make-good negotiated for under-delivery.", "Q4 seasonality expected to lift CPMs.",
    "Brand safety settings reviewed with client.", "Requires finance approval above threshold.",
    "Carry-over from previous fiscal year.", "Renewal discussion scheduled for next QBR.",
    "Discrepancy under investigation with ad server.", "Invoice matched to IO and delivery report.",
]
REASONS = [
    "Client budget change", "Scope adjustment", "Timeline shift", "Rate renegotiation",
    "Under-delivery", "Creative delays", "Change in KPI targets", "Vendor substitution",
    "Fiscal year re-forecast", "Compliance review outcome", "Duplicate entry", "Client request",
]
DESCRIPTIONS = [
    "Standard terms as agreed in the master services agreement.",
    "Covers planning, buying and reporting for paid media.",
    "Includes creative development and asset production.",
    "Applies to all digital channels unless otherwise stated.",
    "Measured monthly against the agreed baseline.",
    "Defined jointly with the client marketing team.",
]
GEO_TARGETS = ["US", "US; CA", "US - Northeast", "US - West Coast", "US top 25 DMAs", "US, CA, GB", "US - South"]
DEVICE_TARGETS = ["all_devices", "desktop, mobile", "mobile only", "ctv", "desktop, mobile, tablet"]
DAYPARTS = ["Mon-Fri 06:00-22:00", "All day", "Weekends only", "Prime time 19:00-23:00", "Business hours"]
