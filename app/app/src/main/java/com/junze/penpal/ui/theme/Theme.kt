package com.junze.penpal.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Warm cream + orange palette, matching the app icon.
val CreamBg = Color(0xFFFFF7E8)
val CreamSurface = Color(0xFFFFFDF6)
val CreamCard = Color(0xFFFFFBF0)
val OrangePrimary = Color(0xFFE8833A)
val OrangeLight = Color(0xFFF6A96B)
val OrangeDark = Color(0xFFC96A1E)
val AmberDark = Color(0xFF8A5A2B)
val TextDark = Color(0xFF3D2C1E)
val TextMuted = Color(0xFF8C7A66)
val DividerColor = Color(0xFFF0DFC8)
val SuccessGreen = Color(0xFF5A9A5A)

private val LightColors = lightColorScheme(
    primary = OrangePrimary,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFFFE3C7),
    onPrimaryContainer = AmberDark,
    secondary = AmberDark,
    onSecondary = Color.White,
    background = CreamBg,
    onBackground = TextDark,
    surface = CreamSurface,
    onSurface = TextDark,
    surfaceVariant = CreamCard,
    onSurfaceVariant = TextMuted,
    outline = DividerColor,
    error = Color(0xFFB3261E)
)

// The app is designed light-only (cream); dark theme reuses the same warm
// scheme so cards always look the same.
private val DarkColors = darkColorScheme(
    primary = OrangePrimary,
    onPrimary = Color.White,
    primaryContainer = Color(0xFF5A3410),
    onPrimaryContainer = Color(0xFFFFE3C7),
    secondary = OrangeLight,
    onSecondary = TextDark,
    background = Color(0xFF2A1F14),
    onBackground = Color(0xFFFFF3DF),
    surface = Color(0xFF332619),
    onSurface = Color(0xFFFFF3DF),
    surfaceVariant = Color(0xFF3D2E1D),
    onSurfaceVariant = Color(0xFFD8C4A8),
    outline = Color(0xFF6B543A),
    error = Color(0xFFFFB4AB)
)

private val AppTypography = Typography(
    headlineMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Bold,
        fontSize = 22.sp,
        lineHeight = 28.sp
    ),
    titleLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Bold,
        fontSize = 18.sp,
        lineHeight = 24.sp
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Bold,
        fontSize = 16.sp,
        lineHeight = 22.sp
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 22.sp
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 18.sp
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.Default,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp
    )
)

@Composable
fun PenpalTheme(content: @Composable () -> Unit) {
    val colors = if (isSystemInDarkTheme()) DarkColors else LightColors
    MaterialTheme(
        colorScheme = colors,
        typography = AppTypography,
        content = content
    )
}
