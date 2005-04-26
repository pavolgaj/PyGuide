#!/usr/local/bin/python
"""StarShape

Fit a a star to a symmetrical double gaussian.

Uses an algorithm developed by Jim Gunn:
- Model the star as a double gaussian: a main gaussian
plus a small contribution from a gaussian of 1/10 the amplitude
and twice the sigma. (When we speak of sigma or fwhm we mean
the sigma or fwhm of the main gaussian.)
- Try different widths by walking along a table that spans
the space fwhm = [1, 1.5, ... 20] pixels. Note that the table
actually contains width parameter values, where wp = 1 / sigma**2.

Note: the gaussian function is:
C * e**-(x-xo)**2/(2 * sigma**2)
where:
C = 1 / (sigma * sqrt(2 pi))

The full width at half maximum is given by:
fwhm = 2 * sqrt(2 * ln(2)) * sigma ~= 2.35 * sigma

This code is based on an algorithm and code by Jim Gunn,
with refinements by Connie Rockosi.

Note: Jim's original code uses a clever trick to avoid recomputing
the model profile. It computes the model profile once at a large
number of points, then picks which of those points to use
based on the trial star width. I omitted that trick because I felt
it was easier (and fast enough) to compute a new model profile
for each trial width.

Refinements include:
- The final amplitude, background and chiSq are computed
based on the final width. The original code computed
ampl, bkgnd and chiSq at various width parameters,
then used a parbolic fit to compute a final width
and a final chiSq (but not a final ampl and bkgnd).
As a result, chiSq could be negative in extreme cases.

To do:
- Normalize the chiSq function and possibly refine it.
I tried various alternative weightings including:
nPts(rad)**2 / var(rad)
nPts(rad) / var(rad)
nPts(rad) > 1
but none did any better than nPts.

History:
2004-05-20 ROwen
2004-06-03 ROwen	Modified the module doc string.
2004-07-02 ROwen	Improved the error estimate.
					Changed GStarFit.err to chiSq
2004-08-03 ROwen	Renamed GStarFit->StarShapeData.
					Modified to use Constants.FWHMPerSigma.
2004-08-04 ROwen	Improved calculation of ij pixel index and position.
					Simplified final computation of minimum width parameter.
					If shape computation fails, converts ArithmeticError into RuntimeError
2004-08-06 ROwen	Fixed invalid variable reference when _FitRadProfIterDebug true. 
2004-12-01 ROwen	Modified StarShapeData to use NaN as the default for each argument.
					Added __all__.
2005-02-07 ROwen	Changed starShape argument ctr (i,) to xyCtr.
2005-04-01 ROwen	Added required argument rad and optional argument bkgnd.
					No longer iterate the fit with an updated predFWHM because
					it doesn't seem to help when the data radius is fixed.
					Added constant _MinRad to constrain the minimum radius.
2005-04-04 ROwen	Bug fix: mis-handled case of bkgnd not specified.
2005-04-15 ROwen	Temporarily hacked the weighting function to see if it makes things better.
					Added pylab (matplotlib) debugging graphs.
2005-04-22 ROwen	Modified to use nPts as the weighting function.
					This seems to work slightly better than nPts > 1
					and just as well as a combination of nPts and a very crude estimate of S/N.
2005-04-25 ROwen	Updated doc string to state that nPts is the weighting function.
					Removed givenBkgnd argument; it only causes trouble.
"""
__all__ = ["StarShapeData", "starShape"]

import math
import numarray as num
import numarray.ma
import radProf as RP
from Constants import FWHMPerSigma, NaN
import ImUtil

# minimum radius
_MinRad = 3.0

# range of FWHM that is explored
_FWHMMin = 1.0
_FWHMMax = 30.0
_FWHMDelta = 0.25

# constants that may want to be ditched
_DMax = 4096

# debugging flags
_StarShapeDebug = False
_FitRadProfDebug = False
_FitRadProfIterDebug = False
_StarShapePyLab = False

class StarShapeData:
	"""Guide star fit data
	
	Attributes:
	- ampl		profile amplitude (ADUs)
	- bkgnd		background level (ADUs)
	- fwhm		FWHM (pixels)
	- chiSq		chi squared of fit
	"""
	def __init__(self,
		ampl = NaN,
		fwhm = NaN,
		bkgnd = NaN,
		chiSq = NaN,
	):
		self.ampl = float(ampl)
		self.bkgnd = float(bkgnd)
		self.fwhm = float(fwhm)
		self.chiSq = float(chiSq)


def starShape(
	data,
	mask,
	xyCtr,
	rad,
	predFWHM = None,
):
	"""Fit a double gaussian profile to a star
	
	Inputs:
	- data		a numarray array of signed integer data
	- mask		a numarray boolean array, or None if no mask (all data valid).
				If supplied, mask must be the same shape as data
				and elements are True for masked (invalid data).
	- med		median (used as the background)
	- xyCtr		x,y center of star; use the convention specified by
				PyGuide.Constants.PosMinusIndex
	- rad		radius of data to fit (pixels);
				values less than _MinRad are treated as _MinRad
	- predFWHM	predicted FWHM; if omitted then rad/2 is used.
				You can usually omit this because the final results are not very sensitive
				to predFWHM. However, if the predicted FWHM is much too small
				then starShape may fail or give bad results.
	"""
	if _StarShapeDebug:
		print "starShape: data[%s,%s]; xyCtr=%.2f, %.2f; rad=%.1f" % \
			(data.shape[0], data.shape[1], xyCtr[0], xyCtr[1], rad)

	# compute index of nearest pixel center (pixel whose center is nearest xyCtr)
	ijCtrInd = ImUtil.ijIndFromXYPos(xyCtr)
	
	# compute offset of position from nearest pixel center
	ijCtrFloat = ImUtil.ijPosFromXYPos(xyCtr)
	ijOff = [abs(round(pos) - pos) for pos in ijCtrFloat]
	offSq = ijOff[0]**2 + ijOff[1]**2

	# adjust radius as required
	rad = int(round(max(rad, _MinRad)))

	# compute radial profile and associated data
	radIndArrLen = rad + 2 # radial index arrays need two extra points
	radProf = num.zeros([radIndArrLen], num.Float32)
	var = num.zeros([radIndArrLen], num.Float32)
	nPts = num.zeros([radIndArrLen], num.Long)
	RP.radProf(data, mask, ijCtrInd, rad, radProf, var, nPts)
	
	if _StarShapePyLab:
		global pylab
		import pylab
		pylab.close()
		pylab.subplot(3,1,1)
		pylab.plot(radProf)
		pylab.subplot(3,1,2)
		pylab.plot(nPts)
	
	# fit data
	if predFWHM == None:
		predFWHM = float(rad)
	gsData = _fitRadProfile(radProf, var, nPts, predFWHM)
	if _StarShapeDebug:
		print "starShape: predFWHM=%.1f; ampl=%.1f; fwhm=%.1f; bkgnd=%.1f; chiSq=%.2f" % \
			(predFWHM, gsData.ampl, gsData.fwhm, gsData.bkgnd, gsData.chiSq)
	
	"""Adjust the width for the fact that the centroid
	is not exactly on the center of a pixel
	
	The equivalent sigma^2 of a profile displaced by d from its center
	is sig^2 + d^2/2, so we need to subtract d^2/2 from the sigma^2
	of an offcenter extracted profile to get the true sigma^2.
	Note that this correction is negligable for anything except
	extremely compact stars.
	"""
	rawFWHM = gsData.fwhm
	rawSigSq = (FWHMPerSigma * rawFWHM)**2
	corrSigSq = rawSigSq - (0.5 * offSq)
	gsData.fwhm = math.sqrt(corrSigSq) / FWHMPerSigma
	
	if _StarShapeDebug:
		print "starShape: ijOff=%.2f, %.2f; offSq=%.2f; rawFWHM=%.3f; corrFWHM=%.3f" % \
			(ijOff[0], ijOff[1], offSq, rawFWHM, gsData.fwhm)
		
	return gsData


if _StarShapeDebug:
	print "_WPArr =", _WPArr

	
def _fitRadProfile(radProf, var, nPts, predFWHM):
	"""Fit in profile space to determine the width,	amplitude, and background.
	Returns the sum square error.
	
	Inputs:
	- radProf	radial profile around center pixel by radial index
	- var		variance as a function of radius
	- nPts		number of points contributing to profile by radial index
	- predFWHM	predicted FWHM
	
	Returns a StarShapeData object
	"""
	if _FitRadProfDebug:
		print "_fitRadProfile radProf[%s]=%s\n   nPts[%s]=%s\n   predFWHM=%r" % \
			(len(radProf), radProf, len(nPts), nPts, predFWHM)
	ncell = len(_WPArr)

	chiSqByWPInd = num.zeros([ncell], num.Float)
	npt = len(radProf)
	
	# compute starting width parameter
	# and constrain to be at least 1 away from either edge
	# so we can safely walk one step in any direction
	wpInd = int(_wpIndFromFWHM(predFWHM) + 0.5)
	wpInd = max(1, wpInd)
	wpInd = min(wpInd, len(_WPArr) - 2)

	if _FitRadProfDebug:
		print "_fitRadProfile: predFWHM=%s, predWP=%s, wpInd=%s" % \
			(predFWHM, _wpFromFWHM(predFWHM), wpInd)
	
	iterNum = 0
	direc = 1
	radSq = RP.radSqByRadInd(npt)
	seeProf = None
	
	# This radial weight is the one used by Jim Gunn and it seems to do as well
	# as anything else I tried. however, it results in a chiSq that is not normalized.
	radWeight = nPts
	
	# compute fixed sums
	sumNPts = num.sum(nPts)
	sumRadProf = num.sum(nPts*radProf)
	
	if _StarShapePyLab:
		pylab.subplot(3,1,3)
		pylab.plot(radWeight)
		pylab.subplot(3,1,1)
	
	# fit star shape
	while True:
		# for current guess at wp, do linear least squares to solve for
		# amplitude, background, and evaluate ms error
		
		# obtain current width parameter
		wp = _WPArr[wpInd]
		
		# fit data
		ampl, bkgnd, chiSq, seeProf = _fitIter(radProf, nPts, radWeight, radSq, sumNPts, sumRadProf, seeProf, wp)
		chiSqByWPInd[wpInd] = chiSq
		
		if _StarShapePyLab:
			pylab.plot((ampl * seeProf) + bkgnd)

		if iterNum == 0:
			wpInd += direc
		
		elif iterNum == 1:	
			# We have first two points; We ASSUME that the errors are
			# monotonic, as they should be for reasonable first guesses; we
			# just determine the direction from the change in the errors
			if chiSqByWPInd[wpInd] > chiSqByWPInd[wpInd - direc]:
				# wrong way; back up & change directions
				wpInd -= 2*direc
				direc = -direc
			else:
				# right way, keep going
				wpInd += direc

		else:
			if chiSqByWPInd[wpInd] > chiSqByWPInd[wpInd - direc]:
				# passed minimum; back up and compute final results
				wpInd -= direc
				break					  
			else:
				# just keep truckin'
				wpInd += direc 
		
		if not (0 <= wpInd < ncell):
			raise RuntimeError("wpInd has walked off the edge; wpInd=%s, iterNum=%s" % (wpInd, iterNum))
		iterNum += 1

	b = 0.5 * (chiSqByWPInd[wpInd + 1] - chiSqByWPInd[wpInd - 1])
	a = 0.5 * (chiSqByWPInd[wpInd+1] - 2*chiSqByWPInd[wpInd] + chiSqByWPInd[wpInd-1])
	wpIndMin = wpInd - 0.5 * b / a
	fwhmMin = _fwhmFromWPInd(wpIndMin)
	wpMin = _wpFromFWHM(fwhmMin)
			
	# compute final answers at wpMin
	ampl, bkgnd, chiSq, seeProf = _fitIter(radProf, nPts, radWeight, radSq, sumNPts, sumRadProf, seeProf, wpMin)
			
	if _FitRadProfDebug:
		print "_fitRadProfile: wpInd=%s; iterNum=%s" % (wpInd, iterNum)
		print "_fitRadProfile: chiSqByWPInd[wpInd-1:wpInd+1]=%s; min wpInd=%s" % \
			(chiSqByWPInd[wpInd-1:wpInd+2], wpIndMin)
		print "_fitRadProfile: wp[wpInd-1:wpInd+1]=%s; min wp=%s" % \
			(_WPArr[wpInd-1:wpInd+2], wpMin)
		print "_fitRadProfile: FWHM[wpInd-1:wpInd+1]=%s; min FWHM=%s" % \
			([_fwhmFromWP(wp) for wp in _WPArr[wpInd-1:wpInd+2]], fwhmMin)
		print "_fitRadProfile: ampl=%s, FWHM=%s, bkgnd=%s, chiSq=%s" % \
			(ampl, _fwhmFromWP(wpMin), bkgnd, chiSq)

	# return StarShapeData containing fit data
	return StarShapeData(
		ampl  = ampl * float(_DMax),
		fwhm = fwhmMin,
		bkgnd = bkgnd,
		chiSq = chiSq,
	)

def _fitIter(radProf, nPts, radWeight, radSq, sumNPts, sumRadProf, seeProf, wp):
	# compute the seeing profile for the specified width parameter
	seeProf = _seeProf(radSq, wp, seeProf)
	
	# compute sums
	nPtsSeeProf = nPts*seeProf # temporary array
	sumSeeProf = num.sum(nPtsSeeProf)
	sumSeeProfSq = num.sum(nPtsSeeProf*seeProf)
	sumSeeProfRadProf = num.sum(nPtsSeeProf*radProf)

	if _FitRadProfIterDebug:
		print "_fitIter sumSeeProf=%s, sumSeeProfSq=%s, sumRadProf=%s, sumSeeProfRadProf=%s, sumNPts=%s" % \
			(sumSeeProf, sumSeeProfSq, sumRadProf, sumSeeProfRadProf, sumNPts)

	# compute amplitude and background
	# using standard linear least squares fit equations
	# (predicted value = bkgnd + ampl * seeProf)
	try:
		disc = (sumNPts * sumSeeProfSq) - sumSeeProf**2
		ampl  = ((sumNPts * sumSeeProfRadProf) - (sumRadProf * sumSeeProf)) / disc
		bkgnd = ((sumSeeProfSq * sumRadProf) - (sumSeeProf * sumSeeProfRadProf)) / disc
		# diff is the weighted difference between the data and the model
		diff = radProf - (ampl * seeProf) - bkgnd
		chiSq = num.sum(radWeight * diff**2) / sumNPts
	except ArithmeticError, e:
		raise RuntimeError("Could not compute shape: %s" % e)

	if _FitRadProfIterDebug:
		print "_fitIter: ampl=%s; bkgnd=%s; wp=%s; chiSq=%.2f" % \
			(ampl, bkgnd, wp, chiSq)
	
	return ampl, bkgnd, chiSq, seeProf


def _fwhmFromWP(wp):
	"""Converts width parameter to fwhm in pixels.
	wp is the width parameter: 1/sig**2
	"""
	return FWHMPerSigma / math.sqrt(wp)


def _wpFromFWHM(fwhm):
	"""Converts fwhm in pixels to width parameter in 1/pix^2 (???).
	wp is the width parameter 1/sig^2.
	"""
	return (FWHMPerSigma / fwhm)**2


def _fwhmFromWPInd(wpInd):
	"""Convert wpInd to FWHM.
	wpInd is the integer index to _WPArr,
	but this routine is more flexible in that wpInd can be fractional
	and need not be in range
	"""
	return _FWHMMax - (_FWHMDelta * wpInd)

	
def _wpIndFromFWHM(fwhm):
	"""Convert FWHM to wpInd.
	wpInd is the integer index to _WPArr,
	but this routine returns the nearest franctional wpInd.
	If you want an index, it is up to you to round it to an integer
	and make sure it is in range.
	"""
	return (_FWHMMax - fwhm) / _FWHMDelta


def _makeWPArr():
	"""Compute an array of wp values (wp = 1/sigma**2)
	that spans a reasonable range of FWHM"""
	nPts = int(((_FWHMMax - _FWHMMin) / _FWHMDelta) + 0.5)
	wpArr = [_wpFromFWHM(_fwhmFromWPInd(wpInd)) for wpInd in range(nPts)]
	return num.array(wpArr, num.Float32)

def _seeProf(radSq, wp, seeProf=None):
	"""Computes the predicted star profile for the given width parameter.
	
	Inputs:
	- radSq		array of radius squared values
	- wp		desired width parameter = 1/sigma**2
	- seeProf	if specified, the array to fill with new values;
				must be the same length as radSq
	"""
	norm = float(_DMax)/1.1
	
#	# create the output array, if necessary
#	if seeProf == None:
#		seeProf = num.zeros([len(radSq)], num.Int)
#
#	# compute seeprofile; the index is radial index
#	for ind in range(len(radSq)):
#		rsq = radSq[ind]
#		x = -0.5 * rsq * wp
#		seeProf[ind] = int(norm*(math.exp(x) + 0.1*math.exp(0.25*x)) + 0.5)
	
	x = radSq * (-0.5 * wp)
	seeProf = ((num.exp(x) + 0.1*num.exp(0.25*x)) * norm + 0.5).astype(num.Int32)

	return seeProf

_WPArr = _makeWPArr()
