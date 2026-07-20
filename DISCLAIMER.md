# Disclaimer and responsible use

This is an independent, experimental software tool. It is not affiliated with,
endorsed by, sponsored by, or supported by Google. Google Maps, Street View, and
related names and marks belong to their respective owners.

Use this software at your own risk. You are solely responsible for deciding
whether and how to use it, for the requests you make, for the data and imagery
you access or retain, and for complying with all applicable laws, third-party
rights, website instructions, and contractual terms. Those include, where
applicable, the [Google Terms of Service](https://policies.google.com/terms), the
[Google Maps/Earth Additional Terms of Service](https://www.google.com/help/terms_maps_no_navigation.html),
and Google's [Geo Guidelines](https://about.google/brand-resource-center/products-and-services/geo-guidelines/).

This project does not grant permission to access, copy, cache, publish,
redistribute, or commercially exploit any third-party service or content. Do not
use it to bypass access controls or protective measures, evade restrictions,
misrepresent the source of a service, violate machine-readable instructions, or
infringe privacy, intellectual-property, attribution, or other rights. A local
configuration option or technical capability is not a statement that a
particular use is permitted.

## Accountless access and public-data cases

Normal operation of this software is accountless. It does not ask for a Google
account, imported Google cookies, OAuth credentials, or an official Maps API
key. Its HTTP paths do not supply account credentials, and its optional browser
backend starts with a fresh temporary profile rather than an operator's Chrome
profile. This is designed to avoid account-only content and reliance on
permission granted to a particular account.

That design choice can matter to a legal analysis. In
[*Meta Platforms, Inc. v. Bright Data Ltd.*](https://www.govinfo.gov/content/pkg/USCOURTS-cand-3_23-cv-00077/pdf/USCOURTS-cand-3_23-cv-00077-7.pdf),
No. 23-cv-00077-EMC (N.D. Cal. Jan. 23, 2024), the court construed
Meta's particular terms not to prohibit Bright Data's logged-off collection of
publicly available Facebook and Instagram data. In
[*hiQ Labs, Inc. v. LinkedIn Corp.*](https://cdn.ca9.uscourts.gov/datastore/opinions/2022/04/18/17-16783.pdf),
31 F.4th 1180 (9th Cir. 2022), the Ninth Circuit held, at the preliminary-
injunction stage, that hiQ raised serious questions about whether accessing
information open to the general public was "without authorization" under the
Computer Fraud and Abuse Act.

Neither decision establishes that all logged-out automation is lawful. The Meta
decision is a federal district-court ruling about Meta's wording and evidence;
it did not interpret Google's terms or create a nationwide rule. The hiQ ruling
addressed one federal statute, in one circuit, on a preliminary record. Other
claims can involve contract formation and scope, copyright, privacy, trespass,
unfair competition, state computer-access laws, rate or access-control evasion,
and how retrieved material is stored, displayed, or redistributed.

Google's terms are also materially different from the Meta terms interpreted in
that case. Google's [U.S. Terms of Service](https://policies.google.com/terms)
expressly state that they apply when services are accessed whether the user is
signed in or not. The
[Google Maps/Earth Additional Terms](https://www.google.com/help/terms_maps_no_navigation.html)
include restrictions concerning automated retrieval, copying, redistribution,
mass downloads, bulk feeds, and places databases. Google's
[Geo Guidelines](https://about.google/brand-resource-center/products-and-services/geo-guidelines/)
also impose attribution and use restrictions, including specific limits on
Street View imagery. Whether those provisions apply or are enforceable in a
particular situation is fact- and jurisdiction-dependent.

The accurate conclusion is therefore narrower: accountless access to publicly
reachable material may reduce some legal risks and may support arguments under
cases such as *Meta v. Bright Data* and *hiQ*, but it does not by itself resolve
whether a particular use of this tool is lawful. This section is general
information, not legal advice. It was last reviewed on July 19, 2026.

To the maximum extent permitted by applicable law, this software and its output
are provided "as is" and "as available," without warranties of any kind,
including accuracy, reliability, availability, fitness for a particular purpose,
merchantability, or non-infringement. The maintainers and contributors are not
responsible for service changes, blocked accounts or networks, lost data, legal
claims, charges, or other direct or indirect consequences arising from use of
the software, except where liability cannot lawfully be excluded.
