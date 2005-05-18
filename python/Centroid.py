"""Measure centroids.

To do:
- Totally debug the new stuff, especially all the submasking
  and subframing -- in centroid and in basicCentroid
  (code that computes nSat) 
- Consider where we can reuse arrays;
  verify that num.logical_foo(a, b, output) is legit

- Improve the estimate of centroid error.
- Smooth the data before centroiding it to handle cosmic rays.
	Consider either a gaussian smoothing or a median filter.
	In either case, make sure to handle masked pixels correctly.

Warnings:
- Will be thrown off by hot pixels. This could perhaps
be improved by centroiding median-filtered data. The question
is whether the median filtering would adversely affect
centroids, especially for faint objects. This is especially
a concern because at present I have no code to do a proper
median filter of masked data.
- The measure of asymmetry is supposed to be normalized,
but it gets large for bright objects with lots of masked pixels.
This may be simply because the value is only computed at the nearest
integer pixel or because the noise is assumed gaussian, or some error.

The centroid is the point of mimimum radial asymmetry:
	sum over rad of var(rad)^2 / weight(rad)
where weight is the expected sigma of var(rad) due to pixel noise:
	weight(rad) = pixNoise(rad) * sqrt(2(numPix(rad) - 1))/numPix(rad)
	pixNoise(rad) = sqrt((readNoise/ccdGain)^2 + (meanVal(rad)-bias)/ccdGain)

The minimum is found in two stages:
1) Find the pixel with the minimum radAsymm.
The direction to walk is determined by measuring radAsymm at 9 points.
Each step is one pixel along x and/or y.

2) Find the true centroid (to better than one pixel) by applying
a quadratic fit to the 3x3 radAsymm matrix centered on the
pixel of minimum radAsymm. Only the points along +/-x and +/-y
are used for this fit; the diagonals are ignored.

Acknowledgements:
- The centroiding algorithm was invented by Jim Gunn
- The code uses a new asymmetry weighting function
	developed with help from Connie Rockosi
- This code is adapted from the SDSS centroiding code,
	which was written by Jim Gunn and cleaned up by Connie Rockosi.
	
History:
2004-03-22 ROwen	First release.
2004-04-07 ROwen	Packaged as part of PyGuide and moved test code elsewhere.
					Also changed array data types to match changes in radProf.
2004-04-12 ROwen	Modified centroid to return totCounts.
2004-04-16 ROwen	Modified centroid to not return minAsymm.
2004-04-30 ROwen	Modified to truncate initGuess (i.e. anywhere within a pixel
					selects that pixel) and round radius to the nearest integer.
					Bug fix: was converting to Int16 instead of UInt16.
2004-06-03 ROwen	Modified to use the initial guess without modification.
2004-08-03 ROwen	Finally added a measure of centroiding error.
2004-08-06 ROwen	Weight asymmetry calculation by radial noise.
2004-08-25 ROwen	Added _MinRad, to more reliably centroid small stars.
					Added __all__.
2004-10-14 ROwen	Stopped computing several unused variables. Improved import of radProf.
2005-02-07 ROwen	Changed centroid initGuess (i,j) argument to xyGuess.
					Changed returned Centroid data object fields ctr (i,j) to xyCtr, err (i,j) to xyErr.
2005-03-31 ROwen	Improved debug output and the efficiency of the "walked too far" test.
					Noted that rad in CentroidData is integer.
2005-04-01 ROwen	Modified to use round to round the radius instead of adding 0.5 and truncating.
2005-04-11 CLoomis	Added ds9 flag (as per FindStars).
2005-05-17 ROwen	Major overhaul; you will need to code that uses Centroid!
					- Renamed centroid to basicCentroid.
					- Added new centroid as a front end to basicCentroid
						which tests for usable signal and (optionally) for saturated signal.
					- Replaced bias, etc. with ccdGain, a CCDGain object.
					- Renamed ds9 argument to doDS9.
					- Added verbosity argument, which replaces _CTRDEBUG and _CTRITERDBUG.
					- Added isOK and msgStr fields to CentroidData as well as imStats.
					- Both basicCentroid and centroid now almost always return a CentroidData;
						if centroid failed then isOK will be False.
"""
__all__ = ['CCDInfo', 'centroid', 'basicCentroid',]

import math
import sys
import traceback
import warnings
import numarray as num
import numarray.nd_image
import numarray.ma
import radProf
import Constants
import ImUtil

def _fmtList(alist):
	"""Return "alist[0], alist[1], ..."
	"""
	return str(alist)[1:-1]

# minimum radius
_MinRad = 3.0

# amount to add to rad to get outerRad
_OuterRadAdd = 10

# max # of iterations
_MaxIter = 40

class CCDInfo:
	"""Info about the CCD
	
	- bias		ccd bias (ADU)
	- readNoise	ccd read noise (e-)
	- ccdGain	ccd inverse gain (e-/ADU)
	- satLevel	saturation level (ADU); data >= satLevel is saturated;
				None if unknown
	"""
	def __init__(self,
		bias,
		readNoise,
		ccdGain,
		satLevel = (2**16)-1,
	):
		self.bias = bias
		self.readNoise = readNoise
		self.ccdGain = ccdGain
		self.satLevel = satLevel
	
	def __repr__(self):
		dataList = []
		for arg in ("bias", "readNoise", "ccdGain", "satLevel"):
			val = getattr(self, arg)
			if val != None:
				dataList.append("%s=%s" % (arg, val))
		return "CCDInfo(%s)" % ", ".join(dataList)


class ImStats:
	"""Information about the image
	(including the settings use to obtain that info).
	
	Values are None if unknown.
	
	- rad		radius of masked out circular region; None means no central mask
	- outerRad	half width of box of outer region; None means no outer limit
	- med		median
	- stdDev	std dev
	- dataCut	data cut level
	- thresh	threshold used to detect signal
	
	If outerRad != None then med and stdDev are for pixels
	outside a circle of radius "rad" and inside a square
	of size outerRad*2 on a side.
	Otherwise the region used to determine the stats is unknown.
	"""
	def __init__(self,
		rad = None,
		outerRad = None,
		thresh = None,
		med = None,
		stdDev = None,
		dataCut = None,
	):
		self.rad = rad
		self.outerRad = outerRad
		self.thresh = thresh
		self.med = med
		self.stdDev = stdDev
		self.dataCut = dataCut
	
	def __repr__(self):
		dataList = []
		for arg in ("rad", "outerRad", "med", "stdDev", "dataCut", "thresh"):
			val = getattr(self, arg)
			if val != None:
				dataList.append("%s=%s" % (arg, val))
		return "ImStats(%s)" % ", ".join(dataList)


class CentroidData:
	"""Centroid data, including the following fields:
	
	flags; check before paying attention to the remaining data:
	- isOK		if False then centroiding failed and msgStr will say why
	- msgStr	warning or error message (depending on isOK)
	- nSat		number of saturated pixels; None if unknown

	basic info:
	- rad		radius for centroid search (pix)
	- imStats	med, stdDev, etc.; an ImStats object (or None if unknown).
	
	star data:
	- xyCtr		the x,y centroid (pixels); use the convention specified by
				PyGuide.Constants.PosMinusIndex
	- xyErr		the predicted 1-sigma uncertainty in xyCtr (pixels)

	note: the following three values are computed for that radial profile
	centered on the pixel nearest the centroid (NOT the true centroid):

	- asymm		measure of asymmetry:
					sum over rad of var(rad)^2 / weight(rad)
				where weight is the expected sigma of var(rad) due to pixel noise:
					weight(rad) = pixNoise(rad) * sqrt(2(numPix(rad) - 1))/numPix(rad)
					pixNoise(rad) = sqrt((readNoise/ccdGain)^2 + (meanVal(rad)-bias)/ccdGain)
	- pix		the total number of unmasked pixels (ADU)
	- counts	the total number of counts (ADU)
	
	Warning: asymm is supposed to be normalized, but it gets large
	for bright objects with lots of masked pixels. This may be
	simply because the value is only computed at the nearest integer pixel
	or because the noise is assumed gaussian, or some error.
	
	Suggested use:
	- check isOK; if False do not use the data
	- check nSat(); if not None and more than a few then be cautious in using the data
		(I don't know how sensitive centroid accuracy is to # of saturated pixels)
	"""
	def __init__(self,
		isOK = True,
		msgStr = "",
		nSat = None,
		rad = None,
		imStats = None,
		xyCtr = None,
		xyErr = None,
		asymm = None,
		pix = None,
		counts = None,
	):
		self.isOK = isOK
		self.msgStr = msgStr
		self.nSat = nSat
		
		self.rad = rad
		self.imStats = imStats

		self.xyCtr = xyCtr
		self.xyErr = xyErr
		
		self.asymm = asymm
		self.pix = pix
		self.counts = counts


def centroid(
	data,
	mask,
	xyGuess,
	rad,
	ccdInfo,
	thresh = 3.0,
	verbosity = 0,
	doDS9 = False,
):
	"""Check that there is usable signal and then centroid.
	
	Details of usable signal:
	- Computes median and stdDev in a region extending from a circle of radius "rad"
	to a box of size (rad+_OuterRadAdd)*2 on a side.
	- median-smooths the data inside a circle of radius "rad" and makes sure
		there is usable signal: max(data) >= thresh*stdDev + median
	
	Inputs:
	- data		image data [i,j]
	- mask		a mask [i,j] of 0's (valid data) or 1's (invalid); None if no mask.
				If mask is specified, it must have the same shape as data.
	- xyGuess	initial x,y guess for centroid; use the convention specified by
				PyGuide.Constants.PosMinusIndex
	- rad		radius of search (pixels);
				values less than _MinRad are treated as _MinRad
	- ccdInfo	ccd bias, gain, etc.; a CCDInfo object
	- thresh	determines the point above which pixels are considered data;
				valid data >= thresh * standard deviation + median
				values less than PyGuide.Constants.MinThresh are silently increased
	- verbosity	0: no output, 1: print warnings, 2: print information, 3: print iteration info.
				Note: there are no warnings at this time because warnings are returned in the msgStr field.
	- doDS9		if True, display diagnostic images in ds9
	
	Returns a CentroidData object (even if centroiding fails, so always check the isOK flag!).
	"""
	if verbosity > 2:
		print "centroid(xyGuess=%s, rad=%s, thresh=%s)" % (xyGuess, rad, thresh)
	
	outerRad = rad + _OuterRadAdd
	subDataObj = ImUtil.subFrameCtr(
		data,
		xyCtr = xyGuess,
		xySize = (outerRad, outerRad),
	)
	subCtrIJ = subDataObj.subIJFromFullIJ(ImUtil.ijPosFromXYPos(xyGuess))
	subData = subDataObj.getSubFrame().astype(num.UInt16) # force type and copy
	
	if mask != None:
		subMaskObj = ImUtil.subFrameCtr(
			mask,
			xyCtr = xyGuess,
			xySize = (outerRad, outerRad),
		)
		subMask = subMaskObj.getSubFrame().astype(num.Bool) # force type and copy
	else:
		subMask = num.zeros(subData.shape, type=num.Bool)

	thresh = max(Constants.MinThresh, float(thresh))

	# create circleMask; a centered circle of radius rad
	# with 0s in the middle and 1s outside
	radSq = rad**2
	def makeCircle(i, j):
		return ((i-subCtrIJ[0])**2 + (j-subCtrIJ[1])**2) > rad**2
	circleMask = num.fromfunction(makeCircle, subData.shape)
	
	# make a copy of the data outside a circle of radius "rad";
	# use this to compute background stats
	bkgndPixels = num.ma.array(
		subData,
		mask = num.logical_or(subMask, num.logical_not(circleMask)),
	)
	med, stdDev = ImUtil.skyStats(bkgndPixels)
	dataCut = med + (thresh * stdDev)
	# free unused arrays
	del(bkgndPixels)

	imStats = ImStats(
		rad = rad,
		outerRad = outerRad,
		thresh=thresh,
		med = med,
		stdDev = stdDev,
		dataCut = dataCut,
	)

	# median filter the inner data and look for signal > dataCut
	dataPixels = num.ma.array(
		subData,
		mask = num.logical_or(subMask, circleMask),
	)
	smoothedData = dataPixels.filled(med)
	num.nd_image.median_filter(smoothedData, 3, output=smoothedData)
	del(dataPixels)
	
	# look for a blob of at least 2x2 adjacent pixels with smoothed value >= dataCut
	# note: it'd be much simpler but less safe to simply test:
	#    if max(smoothedData) < dataCut: # have signal
	shapeArry = num.ones((3,3))
	labels, numElts = num.nd_image.label(smoothedData>dataCut, shapeArry)
	del(smoothedData)
	slices = num.nd_image.find_objects(labels)
	for ijSlice in slices:
		ijSize = [slc.stop - slc.start for slc in ijSlice]
		if 1 not in ijSize:
			break
	else:
		# no usable signal
		return CentroidData(
			isOK = False,
			msgStr = "No signal",
			rad = rad,
			imStats = imStats,
		)

	return basicCentroid(
		data = data,
		mask = mask,
		xyGuess = xyGuess,
		rad = rad,
		ccdInfo = ccdInfo,
		imStats = imStats,
		verbosity = verbosity,
		doDS9 = False,
	)


def basicCentroid(
	data,
	mask,
	xyGuess,
	rad,
	ccdInfo,
	imStats = None,
	verbosity = 0,
	doDS9 = False,
):
	"""Compute a centroid.

	Inputs:
	- data		image data [i,j]
	- mask		a mask [i,j] of 0's (valid data) or 1's (invalid); None if no mask.
				If mask is specified, it must have the same shape as data.
	- xyGuess	initial x,y guess for centroid; use the convention specified by
				PyGuide.Constants.PosMinusIndex
	- rad		radius of search (pixels);
				values less than _MinRad are treated as _MinRad
	- ccdInfo	ccd bias, gain, etc.; a CCDInfo object
	- imStats	image statistics such as median and std. dev. (if known); an ImStats object
	- verbosity	0: no output, 1: print warnings, 2: print information, 3: print iteration info.
				Note: there are no warnings at this time because the relevant info is returned.
	- doDS9		if True, diagnostic images are displayed in ds9
		
	Returns a CentroidData object (which see)
	"""
	# convert input data to UInt16 and make contiguous, if necessary, to speed radProf call
	if data.type() != num.UInt16:
		if verbosity > 2:
			print "basicCentroid: converting data to UInt16"
		data = data.astype(num.UInt16)
	elif not data.iscontiguous():
		if verbosity > 2:
			print "basicCentroid: copying data to make it contiguous"
		data = data.copy()

	# round the initial guess and radius to the nearest integer
	if len(xyGuess) != 2:
		raise ValueError("initial guess=%r must have 2 elements" % (xyGuess,))
	ijIndGuess = ImUtil.ijIndFromXYPos(xyGuess)
	rad = int(round(max(rad, _MinRad)))
	
	if doDS9:
		ds9Win = ImUtil.openDS9Win()
	else:
		ds9Win = None

	if ds9Win:
		# show masked data in frame 1 and unmasked data in frame 2
		ds9Win.xpaset("tile frames")
		ds9Win.xpaset("frame 1")
		if mask != None:
			ds9Win.showArray(data * (1-mask))
		else:
			ds9Win.showArray(data)
		ds9Win.xpaset("frame 2")
		ds9Win.showArray(data)
		ds9Win.xpaset("frame 1")

		# display circle showing the centroider input in frame 1
		args = list(xyGuess) + [rad]
		ds9Win.xpaset("regions", "image; circle %s # group=ctrcirc" % _fmtList(args))
	
	try:
		# OK, use this as first guess at maximum. Extract radial profiles in
		# a 3x3 gridlet about this, and walk to find minimum fitting error
		maxi, maxj = ijIndGuess
		radSq = rad**2
		asymmArr = num.zeros([3,3], num.Float64)
		totPtsArr = num.zeros([3,3], num.Int32)
		totCountsArr = num.zeros([3,3], num.Float64)
		
		niter = 0
		while True:
			niter += 1
			if niter > _MaxIter:
				raise RuntimeError("could not find a star in %s iterations" % (niter,))
			
			for i in range(3):
				ii = maxi + i - 1
				for j in range(3):
					jj = maxj + j - 1
					if totPtsArr[i, j] != 0:
						continue
					asymmArr[i, j], totCountsArr[i, j], totPtsArr[i, j] = radProf.radAsymmWeighted(
						data, mask, (ii, jj), rad, ccdInfo.bias, ccdInfo.readNoise, ccdInfo.ccdGain)
# this version omits noise-based weighting
# (warning: the error estimate will be invalid and chiSq will not be normalized)
#				asymmArr[i, j], totCountsArr[i, j], totPtsArr[i, j] = radProf.radAsymm(
#					data, mask, (ii, jj), rad)
	
					if verbosity > 3:
						print "basicCentroid: asymm = %10.1f, totPts = %s, totCounts = %s" % \
							(asymmArr[i, j], totPtsArr[i, j], totCountsArr[i, j])
	
			# have error matrix. Find minimum
			ii, jj = num.nd_image.minimum_position(asymmArr)
			ii -= 1
			jj -= 1
	
			if verbosity > 2:
				print "basicCentroid: error matrix min ii=%d, jj=%d, errmin=%5.1f" % (ii, jj, asymmArr[ii,jj])
				if verbosity > 3:
					print "basicCentroid: asymm matrix =\n", asymmArr
	
			if (ii != 0 or jj != 0):
				# minimum error not in center; walk and try again
				maxi += ii
				maxj += jj
				if verbosity > 2:
					print "shift by", -ii, -jj, "to", maxi, maxj
	
				if ((maxi - ijIndGuess[0])**2 + (maxj - ijIndGuess[1])**2) >= radSq:
					raise RuntimeError("could not find star within %r pixels" % (rad,))
				
				# shift asymmArr and totPtsArr to minimum is in center again
				asymmArr = num.nd_image.shift(asymmArr, (-ii, -jj))
				totCountsArr = num.nd_image.shift(totCountsArr, (-ii, -jj))
				totPtsArr = num.nd_image.shift(totPtsArr, (-ii, -jj))
			else:
				# Have minimum. Get out and go home.
				break
	
		if verbosity > 2:
			print "basicCentroid: after %r iterations computing final quantities" % (niter,)
		
		# perform a parabolic fit to find true centroid
		# and compute the error estimate
		# y(x) = ymin + a(x-xmin)^2
		# a = (y0 - 2y1 + y2) / 2
		# xmin = b/2a where b = (y2-y0)/2
		# ymin = y1 - b^2/4a  but this is tricky in 2 dimensions so we punt
		# for a given delta-y, delta-x = sqrt(delta-y / a)
		ai = 0.5 * (asymmArr[2, 1] - 2.0*asymmArr[1, 1] + asymmArr[0, 1])
		bi = 0.5 * (asymmArr[2, 1] - asymmArr[0, 1])
		aj = 0.5 * (asymmArr[1, 2] - 2.0*asymmArr[1, 1] + asymmArr[1, 0])
		bj = 0.5 * (asymmArr[1, 2] - asymmArr[1, 0])
	
#	print "asymmArr[1-3]=", asymmArr[0,1], asymmArr[1,1], asymmArr[2,1], "ai, aj=", ai, aj
		
		di = -0.5*bi/ai
		dj = -0.5*bj/aj
		ijCtr = (
			maxi + di,
			maxj + dj,
		)
		xyCtr = ImUtil.xyPosFromIJPos(ijCtr)
		
		# crude error estimate, based on measured asymmetry
		# note: I also tried using the minimum along i,j but that sometimes is negative
		# and this is already so crude that it's not likely to help
		radAsymmSigma = asymmArr[1,1]
		iErr = math.sqrt(radAsymmSigma / ai)
		jErr = math.sqrt(radAsymmSigma / aj)
	
		if ds9Win:
			# display x at centroid
			ds9Win.xpaset("regions", "image; x point %s # group=centroid" % \
						_fmtList(xyCtr))
	

		# count # saturated pixels, if satLevel available
		if ccdInfo.satLevel == None:
			nSat = None
		else:
			intXYCtr = [int(val) for val in xyCtr]
			subRad = rad+1
			subDataObj = ImUtil.subFrameCtr(
				data,
				xyCtr = intXYCtr,
				xySize = (subRad, subRad),
			)
			subData = subDataObj.getSubFrame().astype(num.UInt16) # force type and copy
			subCtrIJ = subDataObj.subIJFromFullIJ(ImUtil.ijPosFromXYPos(xyCtr))

			def makeCircle(i, j):
				return ((i-subCtrIJ[0])**2 + (j-subCtrIJ[1])**2) > rad**2
			maskForData = num.fromfunction(makeCircle, subData.shape)

			if mask != None:
				subMaskObj = ImUtil.subFrameCtr(
					mask,
					xyCtr = intXYCtr,
					xySize = (subRad, subRad),
				)
				subMask = subMaskObj.getSubFrame().astype(num.Bool)
				num.logical_or(maskForData, subMask, maskForData)
			
			hotPixels = num.logical_and(subData >= ccdInfo.satLevel, num.logical_not(maskForData))
			nSat = num.nd_image.sum(hotPixels)
	
		return CentroidData(
			isOK = True,
			rad = rad,
			nSat = nSat,
			imStats = imStats,
			xyCtr = xyCtr,
			xyErr = (jErr, iErr),
			counts = totCountsArr[1,1],
			pix = totPtsArr[1,1],
			asymm = asymmArr[1,1],
		)
	except (SystemExit, KeyboardInterrupt):
		raise
	except Exception, e:
		if verbosity >= 1:
			traceback.print_exc(file=sys.stderr)
		return CentroidData(
			isOK = False,
			msgStr = str(e),
			rad = rad,
			imStats = imStats,
		)