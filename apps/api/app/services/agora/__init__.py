"""Agora RTC token minting.

Vendored copies of Agora's official AccessToken2 builder live alongside this
package (AccessToken2.py, RtcTokenBuilder2.py, Packer.py). The public entry
point is mint_rtc_token in tokens.py — domain code never touches the builders
directly, and the App Certificate stays server-side only.
"""
